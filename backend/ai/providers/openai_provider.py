import os

from openai import OpenAI

from ..provider import AIProvider

SYSTEM_PROMPT = """You are a tactical advisor for Elite Dangerous Power Play operations.
In Elite Dangerous, Powers control systems across the galaxy. Commanders help their Power by:
- Fortifying: delivering commodities to controlled systems to protect them from undermining
- Expanding: delivering commodities to new systems to bring them under their Power's control

Undermined systems generate less revenue and are at risk of losing control. Turmoil means a system may be lost.
Expansion and InPrepareRadius states mean a system is actively being contested or prepared for expansion.

When given a list of recommended systems, produce a concise tactical briefing (2-3 sentences) \
summarizing the most urgent priorities. Be specific about system names and states. \
Write for a Commander who wants to know what to do first."""


class OpenAIProvider(AIProvider):
    def __init__(self, base_url: str | None = None, model: str | None = None):
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o")
        self.max_tokens = int(os.getenv("AI_MAX_TOKENS", "512"))
        self.client = OpenAI(
            api_key=os.getenv("AI_API_KEY"),
            base_url=base_url,  # None uses the default OpenAI endpoint
            # Explicit cap — SDK default is 600s, far too long for a request-path call.
            timeout=float(os.getenv("AI_TIMEOUT_SECONDS", "30")),
        )

    def summarize_recommendations(
        self,
        faction_name: str,
        center_system: str | None,
        fortify_list: list[dict],
        expand_list: list[dict],
    ) -> str:
        center_str = f" (centered on {center_system})" if center_system else ""

        fortify_text = "\n".join(
            f"- {item['system_name']} (score {item['score']:.0f}): "
            f"{', '.join(item['reasons'][:2])}"
            for item in fortify_list[:5]
        ) or "None"

        expand_text = "\n".join(
            f"- {item['system_name']} (score {item['score']:.0f}): "
            f"{', '.join(item['reasons'][:2])}"
            for item in expand_list[:5]
        ) or "None"

        user_message = (
            f"Faction: {faction_name}{center_str}\n\n"
            f"TOP FORTIFICATION PRIORITIES:\n{fortify_text}\n\n"
            f"TOP EXPANSION TARGETS:\n{expand_text}\n\n"
            f"Provide a tactical briefing."
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            max_completion_tokens=self.max_tokens,
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()
