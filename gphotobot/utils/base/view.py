from abc import ABC, abstractmethod
from functools import partial
import inspect
import logging
from typing import Awaitable, Callable, Iterable, Optional

from discord import ButtonStyle, Embed, Interaction, SelectOption, ui
from discord.ext.commands import Bot

from gphotobot.utils import utils

_log = logging.getLogger(__name__)


class BaseView(ui.View, ABC):
    def __init__(self,
                 interaction: Interaction[Bot],
                 callback: Optional[Callable[..., Awaitable[None]]] = None,
                 callback_cancel: Optional[Callable[...,
                 Awaitable[None]]] = None) -> None:
        """
        Initialize the base view.

        Args:
            interaction: The interaction used by this view whenever the display
            is refreshed. Often, this is the interaction of a parent view.
            callback: The function to call when this view is "submitted" or
            "saved" or the user clicks "done." It is asynchronous. This can be
            omitted with no effect, as it's only used by the subclass.
            callback_cancel: A separate function to call when this view is
            cancelled. Defaults to None.
        """

        super().__init__(timeout=None)
        self.interaction: Interaction[Bot] = interaction
        self.callback = callback
        self.callback_cancel = callback_cancel

    @abstractmethod
    async def build_embed(self) -> Optional[Embed]:
        """
        Build the embed for this view.

        Returns:
            The embed, or None if this view doesn't use embeds.
        """

        pass

    async def refresh_display(self) -> None:
        """
        Refresh this view's display by editing the interaction message.
        """

        await self.interaction.edit_original_response(
            content='', embed=await self.build_embed(), view=self
        )

    def create_button(self,
                      label: str,
                      style: ButtonStyle,
                      callback: Callable[[Interaction], Awaitable],
                      emoji: Optional[str] = None,
                      disabled: bool = False,
                      row: Optional[int] = None,
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
            This is typically used if the list of options are strings. These
            default values are the labels.
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
