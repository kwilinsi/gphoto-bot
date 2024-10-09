import asyncio
from collections import defaultdict
import logging

import gphoto2 as gp

from gphotobot.sql import async_session_maker
from . import GCamera, NoCameraFound

_log = logging.getLogger(__name__)

# This is a list of all accessible cameras indexed by their system name.
# It's updated by all_cameras()
_CAMERAS: list[GCamera] = []


def _is_cached(camera: tuple[str, str]) -> bool:
    """
    Determine whether the given camera is in the cache.

    Args:
        camera: The camera to check.

    Returns:
        bool: Whether the camera is in the cache.
    """

    for cam in _CAMERAS:
        if cam.name == camera[0] and cam.name == camera[1]:
            return True

    return False


async def _auto_detect_cameras() -> tuple[
    gp.PortInfoList, gp.CameraAbilitiesList, list[tuple[str, str]]
]:
    """
    Auto-detect all available cameras, along with the list of port info and
    camera abilities used for initializing said cameras.

    This employs async to avoid blocking on IO as it loads ports, abilities, and
    cameras.

    Returns:
        tuple[gp.PortInfoList, gp.CameraAbilitiesList, list[tuple[str, str]],
        int]: (1) the port info list, (2) the camera abilities list, and (3) a
        list of camera records, which are tuples containing a name and address.
    """

    # Load port info
    port_info_list: gp.PortInfoList = gp.PortInfoList()
    await asyncio.to_thread(port_info_list.load)
    n_p = len(port_info_list)
    _log.debug(f"Loaded {n_p} port info entr{'y' if n_p == 1 else 'ies'}")

    # Load camera abilities
    abilities_list: gp.CameraAbilitiesList = gp.CameraAbilitiesList()
    await asyncio.to_thread(abilities_list.load)
    n_a = len(abilities_list)
    _log.debug(f"Loaded {n_a} camera abilities "
               f"entr{'y' if n_a == 1 else 'ies'}")

    # Auto detect cameras
    camera_list: list[tuple[str, str]] = list(
        await asyncio.to_thread(gp.Camera.autodetect)
    )
    n_c: int = len(camera_list)
    _log.info(f"Auto detected {n_c} camera{'' if n_c == 1 else 's'}")

    return port_info_list, abilities_list, camera_list


def _get_port_abilities(port_info_list: gp.PortInfoList,
                        abilities_list: gp.CameraAbilitiesList,
                        name: str,
                        address: str) -> tuple[gp.PortInfo, gp.CameraAbilities]:
    """
    Get the PortInfo and CameraAbilities associated with a particular
    auto-detected camera.

    Args:
        port_info_list: The port info list.
        abilities_list: The camera abilities list.
        name: The name of the particular camera.
        address: The address of the particular camera.

    Returns:
        tuple[gp.PortInfo, gp.CameraAbilities]: The camera port and abilities.
    """

    port_info: gp.PortInfo = port_info_list[port_info_list.lookup_path(address)]
    abilities: gp.CameraAbilities = abilities_list[
        abilities_list.lookup_model(name)
    ]
    return port_info, abilities


def _add_cameras_to_cache(port_info_list: gp.PortInfoList,
                          abilities_list: gp.CameraAbilitiesList,
                          cameras_to_add: list[tuple[str, str]]) -> None:
    """
    Add a list of auto-detected cameras to the cache, first wrapping them in
    the Pythonic GCamera class.

    Args:
        port_info_list (gp.PortInfoList): The port info list.
        abilities_list (gp.CameraAbilitiesList): The camera abilities list.
        cameras_to_add (list[tuple[str, str]]): The list of cameras to add.
    """

    for name, addr in cameras_to_add:
        port_info, abilities = _get_port_abilities(
            port_info_list, abilities_list, name, addr
        )
        _CAMERAS.append(GCamera(
            name, addr, port_info, port_info_list, abilities,
        ))


def _update_cached_cameras(port_info_list: gp.PortInfoList,
                           abilities_list: gp.CameraAbilitiesList,
                           detected_cameras: list[tuple[str, str]]) -> bool:
    """
    Compare the cached cameras with a list of newly-detected cameras. Look for
    any discrepancies, and resolve them.

    This does NOT sync the cache with the database. That must be done
    separately.

    Args:
        port_info_list: The port info list, used for initializing cameras.
        abilities_list: The camera abilities list, for initializing cameras.
        detected_cameras: The list of detected cameras.

    Returns:
        bool: Whether the cache was modified at all.
    """

    # If the cache is empty, add all the detected cameras to it
    if not _CAMERAS:
        _add_cameras_to_cache(port_info_list, abilities_list, detected_cameras)
        return len(detected_cameras) > 0

    # Otherwise, we need to compare the detected cameras with the ones already
    # cached. To do this, we'll pair up exactly matching cameras between the
    # two lists. Any cameras left over are unmatched and will require more work
    # to resolve.

    cache = _CAMERAS.copy()

    for cam_d in detected_cameras:
        match = None

        for cam_c in cache:
            if cam_c.name == cam_d[0] and cam_c.addr == cam_d[1]:
                match = cam_c
                break

        if match:
            cache.remove(match)
            detected_cameras.remove(cam_d)

    # If there aren't any cameras left in either list, that means they all
    # matched, and we're done
    if not cache and not detected_cameras:
        return False

    # If the only extra cameras are in the detected list, then we got new ones
    # we haven't seen before. Add those, and exit
    if not cache:
        _add_cameras_to_cache(port_info_list, abilities_list, detected_cameras)
        return True

    # If the only extra cameras are in the cached list, then they've simply
    # been disconnected from the system. Remove them from the cache, and exit
    if not detected_cameras:
        for cam in cache:
            _CAMERAS.remove(cam)
        return True

    # Ok, this is the tricky part. We have one or more detected cameras and
    # one or more cached cameras remaining that don't obviously match with each
    # other. It's likely that cameras were unplugged and reconnected, and now
    # they have a new address.

    # Group detected cameras by name
    detected_by_name: defaultdict[str, list[str]] = defaultdict(list)
    for cam_d in detected_cameras:
        detected_by_name[cam_d[0]].append(cam_d[1])

    # Group cached cameras by name
    cache_by_name: defaultdict[str, list[GCamera]] = defaultdict(list)
    for cam_c in cache:
        cache_by_name[cam_c.name].append(cam_c)

    # Now check for matching names where there's only ONE camera with that name
    for name, addresses in detected_by_name.items():
        cameras = cache_by_name[name]
        if len(addresses) != 1 or len(cameras) != 1:
            continue

        # Get the new address and port
        addr = addresses[0]
        port_info: gp.PortInfo = port_info_list[
            port_info_list.lookup_path(addr)
        ]

        # Update the cached camera
        cameras[0].update_address(addr, port_info)

        # Remove these cameras from the main lists
        detected_cameras.remove((name, addr))
        cache.remove(cameras[0])

    # If there are no cameras left, we're done
    if not cache and not detected_cameras:
        return True

    # If there are still detected cameras, but nothing left in the cache, then
    # we simply got new cameras. Add them, and exit.
    if not cache:
        _add_cameras_to_cache(port_info_list, abilities_list, detected_cameras)
        return True

    # If there are only cached cameras left, then they were disconnected from
    # the  system. Remove them, and exit.
    if not detected_cameras:
        for cam in cache:
            _CAMERAS.remove(cam)
        return True

    # If there are still unmatched cameras in both lists, I don't know how to
    # resolve it. This could happen if two cameras with the same name were
    # unplugged and then plugged back into different ports. This might be
    # resolvable by comparing attributes of the cameras, like their serial
    # numbers from the camera summaries, but that's a problem for the future.
    # For now, let's just log a warning and drop the cached entries altogether.

    n_d = len(detected_cameras)
    n_c = len(cache)
    n_s = len(_CAMERAS) - len(cache)
    _log.warning(f"Failed to match {n_d} detected "
                 f"camera{'' if n_d == 1 else 's'} with {n_c} cached "
                 f"camera{'' if n_c == 1 else 's'}: multiple cameras have "
                 f"the same name. {n_s} "
                 f"camera{' was' if n_s == 1 else 's were'} successfully "
                 f"matched/updated.")
    _log.info(f"Removing the unmatched cached camera{'' if n_c == 1 else 's'} "
              f"and replacing {'it' if n_c == 1 else 'them'} with the "
              f"detected camera{'' if n_d == 1 else 's'}")

    # Remove unmatched cached cameras
    for cam in cache:
        _CAMERAS.remove(cam)

    # Add the unmatched detected cameras
    _add_cameras_to_cache(port_info_list, abilities_list, detected_cameras)

    return True


async def all_cameras(force_reload: bool = False) -> list[GCamera]:
    """
    Identify all the currently accessible cameras, and return a list of them.

    If the cache of cameras has any cameras in it, those are used: the cameras
    are not auto-detected again by gphoto, and the database is not queried. Use
    force_reload to ignore this cache.

    Args:
        force_reload (bool): Whether to ignore the cache. Defaults to False.

    Raises:
        NoCameraFound: If there aren't any cameras.

    Returns:
        list[GCamera]: The list of cameras.
    """

    # Use cache if available
    if _CAMERAS and not force_reload:
        return _CAMERAS.copy()

    # Auto detect available cameras
    port_info_list, abilities_list, detected_cameras = \
        await _auto_detect_cameras()

    # If no cameras found, exit
    if not detected_cameras:
        _CAMERAS.clear()
        raise NoCameraFound()

    # Compare the cache with the detected cameras, and resolve any discrepancies
    updated = _update_cached_cameras(
        port_info_list, abilities_list, detected_cameras
    )

    # Update the database if there were any changes
    if updated:
        # Figure out which cameras need to be synced
        cameras = [c for c in _CAMERAS if not c.synced_with_database]
        n = len(cameras)
        _log.info(f"Syncing {n} camera{'' if n == 1 else 's'} with the db...")

        # Sync the cameras
        async with async_session_maker() as session, session.begin():
            for cam in cameras:
                await cam.sync_with_database(session)

    # Return the cameras
    return _CAMERAS.copy()


async def get_camera(name: str) -> list[GCamera]:
    """
    Get a camera by its name.

    Args:
        name: The name of the camera.

    Returns:
        list[GCamera]: All connected cameras that match that name.
    """

    return [c for c in await all_cameras() if c.name == name]


async def get_default_camera() -> GCamera:
    """
    Get the default (first cached) camera.

    Async in case there aren't any cached cameras.

    Returns:
        GCamera: The camera.

    Raises:
        NoCameraFound: If there aren't any cameras.
    """

    _log.debug('Getting camera')

    if _CAMERAS:
        return _CAMERAS[0]
    else:
        return (await all_cameras())[0]
