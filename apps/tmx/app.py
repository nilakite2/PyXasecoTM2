from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App, Component

from . import service, tracklist, video

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "tmx",
    "display_name": "MX",
    "description": "ManiaExchange metadata service and map browsing.",
    "modules": [
        "apps/tmx/service.py",
        "apps/tmx/tracklist.py",
        "apps/tmx/challenge_widget.py",
        "apps/tmx/video.py",
    ],
    "entries": [
        "app/tmx",
    ],
    "provides": [
        "service/tmx",
        "feature/tmxvideo",
    ],
    "depends_on": [
        "platform_core",
    ],
}


class TmxApp(App):
    def __init__(self):
        super().__init__(
            app_id="tmx",
            display_name="MX",
            description="ManiaExchange metadata service and map browsing.",
            depends_on=("platform_core",),
            entry_modules=("app/tmx",),
        )
        self.tmx_surfaces = (
            TmxModuleSurface(
                component_id='tmx.service',
                description='TMX metadata service, site resolution, and TMX chat command surface.',
                module=service,
            ),
            TmxModuleSurface(
                component_id='tmx.tracklist',
                description='Tracklist and challenge-window rendering helpers used by Eyepiece and admin flows.',
                module=tracklist,
            ),
            TmxModuleSurface(
                component_id='tmx.video',
                description='TMX video lookup and GPS command surface.',
                module=video,
            ),
        )
        self.components = self.tmx_surfaces

    def register_runtime(self, aseco: 'Aseco') -> None:
        for component in self._components_for(aseco):
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self._components_for(context.aseco):
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self._components_for(context.aseco)):
            await component.shutdown(context)

    def _components_for(self, aseco):
        # Legacy tracklist/video surfaces depend on the still-unported Eyepiece.
        return self.components[:1] if getattr(aseco, 'is_maniaplanet', False) else self.components


class TmxModuleSurface(Component):
    def __init__(self, component_id: str, description: str, module):
        super().__init__(component_id=component_id, description=description)
        self.module = module

    def register(self, aseco: 'Aseco') -> None:
        register = getattr(self.module, 'register', None)
        if callable(register):
            register(aseco)

    async def startup(self, context) -> None:
        startup = getattr(self.module, 'startup', None)
        if callable(startup):
            await startup(context)

    async def shutdown(self, context) -> None:
        shutdown = getattr(self.module, 'shutdown', None)
        if callable(shutdown):
            await shutdown(context)


APP_CLASS = TmxApp
APP_INSTANCE = TmxApp()


def register(aseco: "Aseco"):
    """Runtime app entry that delegates registration to the app instance."""
    APP_INSTANCE.register_runtime(aseco)
