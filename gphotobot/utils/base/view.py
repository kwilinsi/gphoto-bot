from abc import ABC, abstractmethod
from functools import partial
import inspect
import logging
from typing import Awaitable, Callable, Iterable, Optional

from discord import (ButtonStyle, Embed, Interaction,
                     Member, SelectOption, ui, User)
from discord.ext.commands import Bot

from gphotobot.utils import utils

_log = logging.getLogger(__name__)


class BaseView(ui.View, ABC):
    def __init__(self,
                 interaction: Interaction[Bot],
                 callback: Optional[Callable[..., Awaitable[None]]] = None,
                 callback_cancel: Optional[Callable[...,
                 Awaitable[None]]] = None,
                 restrict_to_owner: bool = True,
                 permission_error_msg: str = '',
                 edit_response: bool = True) -> None:
        """
        Initialize the base view.

        By default, this implements restricts on who can use the view. Only the
        user who triggered the initial interaction can interact with any of
        the components in this view. This can be disabled by setting
        restrict_to_owner to False. If another user tries to interact with a
        component, they'll get an ephemeral error message. It starts "Sorry,
        you do not have permission to do that." To add additional information
        to the error message after this line, include the permission_error_msg
        argument.

        Args:
            interaction: The interaction used by this view whenever the display
            is refreshed. Often, this is the interaction of a parent view.
            callback: The function to call when this view is "submitted" or
            "saved" or the user clicks "done." It is asynchronous. This can be
            omitted with no effect, as it's only used by the subclass.
            callback_cancel: A separate function to call when this view is
            cancelled. Defaults to None.
            restrict_to_owner: Whether to block users who didn't create the view
            from interacting with it. Defaults to True.
            permission_error_msg: Additional information to include in an error
            message when restrict_to_owner is True. Defaults to an empty string.
            edit_response: Whether to edit the original interaction response
            when refreshing the display (True) or send a followup (False).
            Defaults to True.
        """

        super().__init__(timeout=None)

        self.interaction: Interaction[Bot] = interaction

        self.callback = callback
        self.callback_cancel = callback_cancel

        self.restrict_to_owner: bool = restrict_to_owner
        self.permission_error_msg: str = permission_error_msg
        self.edit_response: bool = edit_response

    @property
    def user(self) -> User | Member:
        return self.interaction.user

    @abstractmethod
    async def build_embed(self, *args, **kwargs) -> Optional[Embed]:
        """
        Build the embed for this view.

        Args:
            *args: Optional additional arguments.
            **kwargs: Optional additional keyword arguments.

        Returns:
            The embed, or None if this view doesn't use embeds.
        """

        pass

    async def refresh_display(self, *args, **kwargs) -> None:
        """
        Refresh this view's display by editing the interaction message.

        If self.edit_response is False, this sends a new followup message rather
        than editing the original.

        Args:
            *args: Optional arguments to pass to build_embed().
            **kwargs: Optional keyword arguments to pass to build_embed().
        """

        func = self.interaction.edit_original_response if self.edit_response \
            else self.interaction.followup.send

        await func(
            content='',
            embed=await self.build_embed(*args, **kwargs),
            view=self
        )

    async def interaction_check(self, interaction: Interaction) -> bool:
        """
        Validate incoming interactions. If restrict_to_owner is True, this sends
        an error message whenever someone besides the owner tries to use it and
        prevents the interaction from being passed to any components in the
        view.

        Args:
            interaction: The incoming interaction.

        Returns:
            True if and only if the interaction is accepted.
        """

        # If the interacting user is the owner, or we aren't restricting to the
        # owner, allow the interaction to go through
        if not self.restrict_to_owner or \
                interaction.user.id == self.interaction.user.id:
            return True

        # Send a permission error
        embed = utils.contrived_error_embed(
            title='Permission Denied',
            text="Sorry, you don't have permission to do that. " +
                 self.permission_error_msg
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

        # Log a debug message
        _log.debug(f'Blocked user {interaction.user.display_name} '
                   f'(id {interaction.user.id}) from using a component '
                   f'on a {self.__class__.__name__}')

        # Block this interaction from going through
        return False

    def create_button(self,
                      label: str,
                      style: ButtonStyle,
                      callback: Callable[[Interaction], Awaitable],
                      emoji: Optional[str] = None,
                      disabled: bool = False,
                      row: Optional[int] = None,
                      interaction_check: Optional[Callable[[Interaction],
                      Awaitable[bool]]] = None,
                      add: bool = True,
                      auto_defer: bool = True) -> ui.Button:
        """
        Create a button, and optionally add it to this view.

        Args:
            label: The text on the button shown to the user.
            style: The style of the button.
            callback: The async function to run when this button is clicked.
            emoji: An optional emoji to include in the button, or None to omit
            an emoji. Defaults to None.
            disabled: Whether to disable the button so the user can't click it.
            Defaults to False.
            row: The row in the view, i.e. where to put the button vertically.
            None to place automatically. Defaults to None.
            interaction_check: An async callback to run when this button is
            clicked. It returns a boolean. If that boolean is False,
            the button's callback is not run. Defaults to None.
            add: Whether to add the button to this view. Defaults to True.
            auto_defer: Whether to immediately defer any interactions with the
            button before running the callback function. Defaults to False.

        Returns:
            The newly created button.
        """

        # Create the initial button with given settings
        button = ui.Button(
            label=label,
            style=style,
            emoji=emoji,
            disabled=disabled,
            row=row
        )

        # Overwrite the callback function with the provided one
        button.callback = (callback if not auto_defer else
                           utils.deferred(callback))

        # Override the interaction check if given a callback
        if interaction_check is not None:
            button.interaction_check = interaction_check

        # Add the button to this view, if specified
        if add:
            self.add_item(button)

        return button

    def create_select_menu(self,
                           placeholder: str,
                           options: list[SelectOption] | list[str],
                           callback: Callable[[Interaction], Awaitable] | \
                                     Callable[[Interaction, ui.Select],
                                     Awaitable],
                           min_values: int = 1,
                           max_values: int = 1,
                           no_maximum: bool = False,
                           row: Optional[int] = None,
                           defaults: Optional[list[str]] = None,
                           interaction_check: Optional[Callable[[Interaction],
                           Awaitable[bool]]] = None,
                           add: bool = True,
                           auto_defer: bool = True) -> ui.Select:
        """
        Create a dropdown selection menu, and optionally add it to this view.

        Args:
            placeholder: The text shown to the user when nothing is selected.
            options: The list of options for the user to choose from. This can
            either be complete SelectOptions or for a simple menu, a list of
            strings. In the latter case, the strings are used as the labels of
            the options.
            callback: The async function to run when the user selects options.
            This can either accept and interaction or an interaction and the
            newly created selection menu.
            min_values: The minimum number of options that must be selected.
            Must be between 0 and 25. Defaults to 1.
            max_values: The maximum number of options that can be selected.
            Must be between 1 and 25. Defaults to 1.
            no_maximum: Whether to disable the maximum number of options,
            thereby allowing the user to select every option at once. If this
            is True, the max_values parameter is ignored. Defaults to False.
            row: The row in which to place this menu, or None to place
            automatically. Note that select menus take up an entire row.
            Defaults to None.
            defaults: An optional list of options to make selected by default.
            This is typically used if the list of options are strings (which
            are option labels). Defaults to None.
            interaction_check: An async callback to run when this menu is used.
            It returns a boolean. If that boolean is False, the section menu's
            callback is not run. Defaults to None.
            add: Whether to add the menu to this view. Defaults to True.
            auto_defer: Whether to immediately defer any interactions with the
            button before running the callback function. Defaults to False.

        Returns:
            The newly created menu.

        Raises:
            ValueError: If the list of options is None or empty.
        """

        if not options:
            raise ValueError('No options given for selection menu')

        # If the options are strings, convert them to SelectOptions
        if isinstance(options[0], str):
            options = [SelectOption(label=lbl) for lbl in options]  # noqa

        # Set defaults, if specified
        if defaults:
            for o in options:
                if o.label in defaults:
                    o.default = True

        if no_maximum:
            max_values = len(options)

        # Create the menu
        menu = ui.Select(
            placeholder=placeholder,
            options=options,
            min_values=min_values,
            max_values=max_values,
            row=row
        )

        # Add the callback function, including the Select menu if requested
        if len(inspect.signature(callback).parameters) == 2:
            callback = partial(callback, menu=menu)

        # If enabled, wrap callback with util function to defer the interaction
        if auto_defer:
            menu.callback = utils.deferred(callback)
        else:
            menu.callback = callback

        # Override the interaction check if given a callback
        if interaction_check is not None:
            menu.interaction_check = interaction_check

        # Add it to this view, if enabled
        if add:
            self.add_item(menu)

        return menu

    def add_items(self, items: Optional[Iterable[ui.Item]]) -> None:
        """
        Bulk add multiple items (buttons, etc.) from this view.

        Args:
            items: The items to add. If this is None, nothing happens.
            Individual items that are None are ignored.
        """

        if items is not None:
            for item in items:
                if item is not None:
                    self.add_item(item)

    def remove_items(self, items: Optional[Iterable[ui.Item]]) -> None:
        """
        Bulk remove multiple items (buttons, etc.) from this view.

        Args:
            items: The items to remove. If this is None, nothing happens.
            Individual items that are None are ignored.
        """

        if items is not None:
            for item in items:
                if item is not None:
                    self.remove_item(item)

    async def run_cancel_callback(self, *args, **kwargs) -> None:
        """
        Run the cancel callback. (This assumes that said callback was
        initialized when creating this view). Then, stop() this view.

        Args:
            *args: Positional arguments to pass to the cancel callback.
            **kwargs: Keyword arguments to pass to the cancel callback.
        """

        await self.callback_cancel(*args, **kwargs)
        self.stop()
