"""Stage dispatch and result helpers shared by the local application facade layers.

Feature mixins contribute ``_STAGES`` to shared public operations instead of
overriding them; ``stages_for`` resolves those stages along the MRO and
``run_stages`` runs them. These helpers sit below every feature subpackage, so
none of them needs to import the facade itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, is_dataclass
from enum import Enum
from functools import cache
from typing import Any


def jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [jsonable(item) for item in value]
    return value


@cache
def stages_for(
    cls: type, name: str, *, below: type | None = None
) -> tuple[Callable[..., Any], ...]:
    """Stages for public operation ``name`` contributed by ``cls`` and its bases.

    Each facade layer lists its stages in a ``_STAGES`` mapping. They run in
    method resolution order, outermost first, exactly as the former
    ``super()`` overrides did; with ``below`` only classes after ``below`` in
    the MRO contribute, matching a ``super()`` call made from that class.
    Intermediate facade classes that are instantiated directly therefore keep
    the same behavior as before.
    """
    mro = cls.__mro__
    if below is not None:
        mro = mro[mro.index(below) + 1 :]
    return tuple(
        vars(klass)["_STAGES"][name] for klass in mro if name in vars(klass).get("_STAGES", {})
    )


def given_kwargs(**kwargs: Any) -> dict[str, Any]:
    """Keyword arguments the caller actually supplied (``None`` means omitted).

    Dispatchers forward ``view`` only when given, as the former outermost
    override did; deeper layers never accepted it.
    """
    return {key: value for key, value in kwargs.items() if value is not None}


def run_stages(
    stages: tuple[Callable[..., Any], ...],
    facade: Any,
    terminal: Callable[..., Any],
    /,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Run a public facade operation through its ordered stages.

    Feature layers contribute stages instead of overriding the public method.
    Each stage is called as ``stage(facade, proceed, *args, **kwargs)`` and
    calls ``proceed(...)`` with the arguments the next stage (and finally
    ``terminal``) receives. The exported facade declares each stage tuple in
    the order the former ``super()`` chain ran.
    """
    return run_stages_from(0, stages, facade, terminal, *args, **kwargs)


def run_stages_from(
    index: int,
    stages: tuple[Callable[..., Any], ...],
    facade: Any,
    terminal: Callable[..., Any],
    /,
    *args: Any,
    **kwargs: Any,
) -> Any:
    if index >= len(stages):
        return terminal(*args, **kwargs)

    def proceed(*next_args: Any, **next_kwargs: Any) -> Any:
        return run_stages_from(index + 1, stages, facade, terminal, *next_args, **next_kwargs)

    return stages[index](facade, proceed, *args, **kwargs)
