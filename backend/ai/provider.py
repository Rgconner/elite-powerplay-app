from abc import ABC, abstractmethod


class AIProvider(ABC):
    @abstractmethod
    def summarize_recommendations(
        self,
        faction_name: str,
        center_system: str | None,
        fortify_list: list[dict],
        expand_list: list[dict],
    ) -> str:
        """Generate a natural-language tactical briefing.

        fortify_list and expand_list are the top-5 items as plain dicts
        (system_name, score, reasons, pp_state, influence).
        Returns a plain-text paragraph.
        """
        ...
