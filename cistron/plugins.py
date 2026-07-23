"""
Modular plugin extension hub for CISTRON Phase 6.

Developers register :class:`BasePlugin` implementations to inject custom
scoring metrics, drug-clearance models, or parser rules into
:class:`~cistron.simulation.DualEngineSimulator` timelines without editing
core modules.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Type, TypeVar
import importlib
import logging
import threading

from cistron.simulation import (
    DualEngineSimulator,
    PerturbationHook,
    SimulationConfig,
    SimulationState,
    TrajectoryResult,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound="BasePlugin")


class PluginPhase(Enum):
    """Lifecycle points where plugins may execute."""

    REGISTER = auto()
    BEFORE_RUN = auto()
    BEFORE_STEP = auto()
    AFTER_RUN = auto()


@dataclass
class PluginContext:
    """Shared bag passed through plugin callbacks."""

    extras: Dict[str, Any] = field(default_factory=dict)


class BasePlugin(ABC):
    """
    Extension contract.

    Subclasses implement any subset of lifecycle hooks. Returning a
    :class:`~cistron.simulation.PerturbationHook` from :meth:`step_hook`
    injects mid-integration behaviour (PK washout, custom scoring dumps, …).
    """

    name: str = "base"
    priority: int = 100
    """Lower runs earlier within the same phase."""
    enabled: bool = True

    def on_register(self, registry: "PluginRegistry") -> None:
        """Called once when added to a registry."""

    def before_run(
        self,
        engine: DualEngineSimulator,
        config: SimulationConfig,
        context: PluginContext,
    ) -> None:
        """Invoked immediately before Boolean/ODE integration."""

    def step_hook(self) -> Optional[PerturbationHook]:
        """
        Optional per-step hook merged into DualEngineSimulator perturbation chain.

        Default: no hook.
        """
        return None

    def after_run(
        self,
        engine: DualEngineSimulator,
        trajectory: TrajectoryResult,
        context: PluginContext,
    ) -> None:
        """Invoked after a successful run with the resulting trajectory."""

    def score(
        self,
        trajectory: TrajectoryResult,
        context: PluginContext,
    ) -> Optional[Dict[str, float]]:
        """Optional custom metric map; ``None`` if not applicable."""
        return None


class PluginRegistry:
    """
    Dynamic registry + discovery manager.

    Thread-safe registration; plugins sorted by ``priority`` then ``name``.
    """

    ENTRY_POINT_GROUP = "cistron.plugins"

    def __init__(self) -> None:
        self._plugins: Dict[str, BasePlugin] = {}
        self._lock = threading.RLock()
        self.context = PluginContext()

    def __len__(self) -> int:
        return len(self._plugins)

    def __contains__(self, name: str) -> bool:
        return name in self._plugins

    def register(self, plugin: BasePlugin, *, replace: bool = False) -> "PluginRegistry":
        if not plugin.name:
            raise ValueError("Plugin.name must be non-empty")
        with self._lock:
            if plugin.name in self._plugins and not replace:
                raise ValueError(f"Plugin {plugin.name!r} already registered")
            self._plugins[plugin.name] = plugin
            plugin.on_register(self)
        logger.info("Registered plugin %s (priority=%s)", plugin.name, plugin.priority)
        return self

    def unregister(self, name: str) -> None:
        with self._lock:
            self._plugins.pop(name, None)

    def get(self, name: str) -> BasePlugin:
        with self._lock:
            return self._plugins[name]

    def plugins(self) -> List[BasePlugin]:
        with self._lock:
            items = [p for p in self._plugins.values() if p.enabled]
        return sorted(items, key=lambda p: (p.priority, p.name))

    def collect_step_hooks(self) -> List[PerturbationHook]:
        hooks: List[PerturbationHook] = []
        for plugin in self.plugins():
            hook = plugin.step_hook()
            if hook is not None:
                hooks.append(hook)
        return hooks

    def before_run(self, engine: DualEngineSimulator, config: SimulationConfig) -> None:
        for plugin in self.plugins():
            plugin.before_run(engine, config, self.context)

    def after_run(self, engine: DualEngineSimulator, trajectory: TrajectoryResult) -> None:
        for plugin in self.plugins():
            plugin.after_run(engine, trajectory, self.context)

    def collect_scores(self, trajectory: TrajectoryResult) -> Dict[str, Dict[str, float]]:
        out: Dict[str, Dict[str, float]] = {}
        for plugin in self.plugins():
            scored = plugin.score(trajectory, self.context)
            if scored:
                out[plugin.name] = dict(scored)
        return out

    def attach(self, engine: DualEngineSimulator) -> "PluginRegistry":
        """Wire this registry into a DualEngineSimulator instance."""
        engine.attach_plugins(self)
        return self

    def discover_entry_points(self, *, group: Optional[str] = None) -> List[str]:
        """
        Load plugins advertised under ``cistron.plugins`` entry points.

        Returns names of newly registered plugins. Missing importlib.metadata
        or empty groups are no-ops.
        """
        group = group or self.ENTRY_POINT_GROUP
        loaded: List[str] = []
        try:
            from importlib.metadata import entry_points
        except ImportError:  # pragma: no cover
            return loaded
        eps = entry_points()
        selected: Iterable[Any]
        if hasattr(eps, "select"):
            selected = eps.select(group=group)
        else:  # pragma: no cover - py3.9 style
            selected = eps.get(group, [])  # type: ignore[arg-type]
        for ep in selected:
            try:
                obj = ep.load()
                plugin = obj() if isinstance(obj, type) else obj
                if not isinstance(plugin, BasePlugin):
                    logger.warning("Entry point %s is not a BasePlugin", ep.name)
                    continue
                if not plugin.name:
                    plugin.name = ep.name
                self.register(plugin, replace=True)
                loaded.append(plugin.name)
            except Exception as exc:
                logger.warning("Failed loading plugin entry point %s: %s", ep.name, exc)
        return loaded

    def load_module(self, module_path: str, attr: str = "Plugin") -> BasePlugin:
        """Import ``module_path.attr`` and register the resulting plugin."""
        mod = importlib.import_module(module_path)
        obj = getattr(mod, attr)
        plugin = obj() if isinstance(obj, type) else obj
        if not isinstance(plugin, BasePlugin):
            raise TypeError(f"{module_path}.{attr} is not a BasePlugin")
        self.register(plugin, replace=True)
        return plugin


# ---------------------------------------------------------------------------
# Built-in example plugins (production-ready utilities)
# ---------------------------------------------------------------------------


class FinalConcentrationScorePlugin(BasePlugin):
    """Records final concentrations as a named score vector."""

    name = "final_concentration_score"
    priority = 50
    entity_ids: Optional[Sequence[str]] = None

    def __init__(self, entity_ids: Optional[Sequence[str]] = None, *, name: str = "final_concentration_score") -> None:
        self.entity_ids = entity_ids
        self.name = name

    def score(self, trajectory: TrajectoryResult, context: PluginContext) -> Optional[Dict[str, float]]:
        finals = trajectory.final_concentrations()
        if self.entity_ids is None:
            return {k: float(v) for k, v in finals.items()}
        return {eid: float(finals.get(eid, 0.0)) for eid in self.entity_ids}


class RunMetadataPlugin(BasePlugin):
    """Stamps trajectory.metadata with plugin context extras after each run."""

    name = "run_metadata"
    priority = 10

    def before_run(
        self,
        engine: DualEngineSimulator,
        config: SimulationConfig,
        context: PluginContext,
    ) -> None:
        context.extras["network_name"] = engine.network.name
        context.extras["t_end"] = config.t_end

    def after_run(
        self,
        engine: DualEngineSimulator,
        trajectory: TrajectoryResult,
        context: PluginContext,
    ) -> None:
        trajectory.metadata.setdefault("plugins", {})
        trajectory.metadata["plugins"][self.name] = dict(context.extras)


class CallbackHookPlugin(BasePlugin):
    """
    Wrap an arbitrary ``(state, t) -> None`` callback as a step hook.

    Useful for custom drug-clearance or scoring dumps without a full subclass.
    """

    name = "callback_hook"
    priority = 80

    def __init__(
        self,
        callback: Callable[[SimulationState, float], None],
        *,
        name: str = "callback_hook",
    ) -> None:
        self._callback = callback
        self.name = name

    def step_hook(self) -> Optional[PerturbationHook]:
        cb = self._callback

        def hook(state: SimulationState, t: float) -> None:
            cb(state, t)

        return hook


def create_default_registry(*, with_builtins: bool = True) -> PluginRegistry:
    reg = PluginRegistry()
    if with_builtins:
        reg.register(RunMetadataPlugin())
        reg.register(FinalConcentrationScorePlugin())
    return reg
