"""Librería de voces: agrega voces integradas y voces clonadas persistidas."""

from __future__ import annotations

import json
from pathlib import Path

from .config import Settings
from .schemas import Voice


class VoiceStore:
    """Lista voces integradas (de cada proveedor) y voces clonadas (JSON)."""

    def __init__(self, settings: Settings, manager) -> None:
        self._settings = settings
        self._manager = manager
        self._path = Path(settings.voices_dir) / "voices.json"

    async def list(self) -> list[Voice]:
        voices = await self._builtin()
        voices.extend(self._load_cloned())
        return voices

    async def get(self, voice_id: str) -> Voice | None:
        for voice in await self.list():
            if voice.voice_id == voice_id:
                return voice
        return None

    async def add(self, voice: Voice) -> None:
        voices = [v for v in self._load_cloned() if v.voice_id != voice.voice_id]
        voices.append(voice)
        self._save(voices)

    async def delete(self, voice_id: str) -> bool:
        """Elimina una voz clonada; devuelve False si no existía como clonada."""
        voices = self._load_cloned()
        remaining = [v for v in voices if v.voice_id != voice_id]
        if len(remaining) == len(voices):
            return False
        self._save(remaining)
        return True

    async def _builtin(self) -> list[Voice]:
        result: list[Voice] = []
        for name in self._manager.configured_names():
            try:
                provider = self._manager.get(name)
                result.extend(await provider.list_voices())
            except Exception:
                # Un proveedor que no lista voces no debe romper el resto.
                continue
        return result

    def _load_cloned(self) -> list[Voice]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return [Voice(**item) for item in data]
        except Exception:
            return []

    def _save(self, voices: list[Voice]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps([v.model_dump() for v in voices], ensure_ascii=False, indent=2)
        self._path.write_text(payload, encoding="utf-8")
