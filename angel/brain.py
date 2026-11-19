"""AngelBrainService: Gemini text/vision client with model fallbacks."""

import aiohttp
import asyncio
import base64
import discord
import hashlib
import json
import random
import re
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Set, Tuple
from collections import deque
from . import cost
from .config import (ARABIC_GIF_KEYWORDS, GEMINI_API_KEYS, GIF_ACTION_ENDPOINT, GIF_USER_AGENT, IMAGE_GEN_MODELS,
                     SUPPORTED_GIF_ACTIONS, YURI_ANIME_WHITELIST, _safe_gc_collect, is_mistress,
                     is_romantic_gif, logger)
from .net import get_shared_http_session, read_bounded_stream
from .persona import PROBE_PATTERNS, build_angel_system_prompt, humanize, normalize_arabic_text, trim_emoji
from .quota import QuotaGuard
from .images import remove_bottom_watermark_async, strip_all_control_tags
from .registry import get_bot

# 7. Angel Brain Service


class AIServiceError(Exception):
  pass


def _user_tag(user: Any) -> str:
  """Short, non-reversible caller tag for metrics (`-` when there is no user)."""
  uid = getattr(user, "id", 0) or 0
  return hashlib.sha256(f"angel-metrics:{uid}".encode()).hexdigest()[:12] if uid else "-"


class AngelBrainService:

  def __init__(self, api_key: str, models_list: List[str], quota_guard: QuotaGuard):
    self.api_key = api_key
    self._keys = [k for k in GEMINI_API_KEYS if k] or [api_key]
    self._key_index = 0
    self._cooling = {}
    self.models_list = list(dict.fromkeys(m for m in models_list if m))
    self.active_model = self.models_list[0]
    self.quota_guard = quota_guard
    self.max_retries_per_model = 2
    self.base_delay = 0.7
    self._recent_gif_urls: deque = deque(maxlen=40)
    self.db = None  # injected by bot.py for USD accounting/breaker
    self._dead_models: Set[str] = set()

  def _get_endpoint(self, model_name: str) -> str:
    clean_model = model_name.replace("models/", "").strip()
    return f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent"

  def _cool(self, model: str, seconds: float = 120.0) -> None:
    """Remember a throttled model so the next call does not waste a retry on it."""
    self._cooling[model] = time.monotonic() + seconds

  def _is_cooling(self, model: str) -> bool:
    until = self._cooling.get(model)
    return bool(until and time.monotonic() < until)

  def _active_key(self) -> str:
    return self._keys[self._key_index % len(self._keys)]

  def _rotate_key(self) -> None:
    if len(self._keys) > 1:
      self._key_index = (self._key_index + 1) % len(self._keys)
      logger.warning("gemini key rotated -> slot %d of %d", self._key_index + 1, len(self._keys))

  async def _post_with_retry(self, payload: dict, high_priority: bool = False,
                             cmd: str = "chat", user: Any = None) -> str:
    timeout = aiohttp.ClientTimeout(total=22)

    all_candidates = [self.active_model] + [
        m for m in self.models_list if m != self.active_model
    ]
    candidate_models = [m for m in all_candidates if m not in self._dead_models] or all_candidates

    for model_name in candidate_models:
      if self._is_cooling(model_name):
        logger.info("ai-skip model=%s reason=cooldown", model_name)
        continue
      endpoint = self._get_endpoint(model_name)
      _gen = payload.get("generationConfig")
      if isinstance(_gen, dict) and "thinkingConfig" not in _gen and ("gemini-4" in model_name or "gemini-3.1" in model_name):
        # 4.x/3.1 spend the whole token budget thinking and return an empty answer without this
        _gen["thinkingConfig"] = {"thinkingBudget": 0}
      for attempt in range(1, self.max_retries_per_model + 1):
        if await self.budget_blocked(user):
          logger.info("ai-guard reason=budget")
          if self.db is not None:
            await self.db.add_usage(cost.local_day(), 0, 0, 0.0, blocked=True)
          raise cost.BudgetExhausted("daily budget reached (95%): listening mode")
        await self.quota_guard.pace_global_rpm(high_priority)
        t0 = time.monotonic()
        # Rebuild headers every attempt so a rotated GEMINI_API_KEY_2 actually takes effect.
        headers = {"x-goog-api-key": self._active_key(), "Content-Type": "application/json"}
        try:
          session = await get_shared_http_session()
          async with session.post(endpoint, headers=headers, json=payload, timeout=timeout) as response:
              if response.status == 200:
                elapsed_ms = round((time.monotonic() - t0) * 1000.0, 1)
                self.quota_guard.model_latency_ms[model_name] = elapsed_ms
                if self.active_model != model_name:
                  self.active_model = model_name
                self.quota_guard.model_usage_stats[model_name] += 1
                data = await response.json()
                candidates = data.get("candidates", [])
                if not candidates or "content" not in candidates[0]:
                  raise AIServiceError("أترفع عن الرد على هذا الكلام.")
                parts = candidates[0]["content"].get("parts", [])
                # Exclude internal thinking parts ('thought': True) on Gemini 3.x/2.5 models
                visible_text = "".join(
                    p.get("text", "") for p in parts if "text" in p and not p.get("thought")
                ).strip()
                if not visible_text and parts:
                  visible_text = "".join(p.get("text", "") for p in parts if "text" in p).strip()
                usage = data.get("usageMetadata") or {}
                in_tok = int(usage.get("promptTokenCount") or 0)
                out_tok = int(usage.get("candidatesTokenCount") or 0)
                usd = cost.cost_of(in_tok, out_tok)
                if self.db is not None:
                  await self.db.add_usage(cost.local_day(), in_tok, out_tok, usd)
                logger.info("ai-reply ms=%s model=%s usd=%.6f cmd=%s user=%s",
                            elapsed_ms, model_name, usd, cmd, _user_tag(user))
                return visible_text

              err_snip = (await response.text())[:160]
              self.quota_guard.last_api_error = f"{model_name}: HTTP {response.status}"
              if response.status == 404:
                logger.warning(f"Gemini model '{model_name}' returned 404 NotFound; marking inactive.")
                self._dead_models.add(model_name)
                if self.quota_guard.recent_api_timestamps:
                  self.quota_guard.recent_api_timestamps.pop()
                break
              if response.status == 429:
                logger.warning(f"Gemini model '{model_name}' hit 429 TooManyRequests; failing over to next model.")
                self._cool(model_name)
                self._rotate_key()
                if self.quota_guard.recent_api_timestamps:
                  self.quota_guard.recent_api_timestamps.pop()
                await asyncio.sleep(0.25)
                break
              if response.status in (500, 502, 503, 504):
                logger.warning(f"Gemini model '{model_name}' HTTP {response.status}; switching/retrying.")
                if response.status == 503:
                  self._cool(model_name, 60.0)
                if attempt < self.max_retries_per_model:
                  await asyncio.sleep(0.35)
                  continue
                break
              if response.status == 400 and isinstance(payload.get("generationConfig"), dict) \
                      and "thinkingConfig" in payload["generationConfig"]:
                payload["generationConfig"].pop("thinkingConfig", None)
                continue
              if response.status in (400, 401, 403):
                logger.error(f"Gemini API error HTTP {response.status} on '{model_name}': {err_snip}")
                raise AIServiceError("حدث خلل داخلي أثناء معالجة الطلب.")
              break
        except (aiohttp.ClientError, asyncio.TimeoutError):
          if attempt < self.max_retries_per_model:
            await asyncio.sleep(self.base_delay * attempt)
          else:
            break

    raise AIServiceError("أنا منشغلة حالياً، خاطبني بعد لحظات.")

  async def budget_blocked(self, user: Any = None) -> bool:
    """True once 95% of the daily USD ceiling is spent (listening mode).

    The owner is never locked out of her own bot. A call made by the owner
    keeps working past the ceiling; every other caller is refused as before. The
    override is logged so the overspend is visible instead of silent.
    """
    if self.db is None:
      return False
    if (await self.db.day_cost(cost.local_day())) < cost.stop_at():
      return False
    if is_mistress(user):
      logger.warning(
          "cost-guard owner_override=1 spent=%.4f stop_at=%.4f — owner call admitted past the ceiling",
          await self.db.day_cost(cost.local_day()), cost.stop_at(),
      )
      return False
    return True

  async def generate_angel_reply_raw(self, prompt: str, max_tokens: int = 220, temperature: float = 0.5,
                                     user: Any = None) -> str:
    """One-shot generation for utility answers (rules, summaries) with the cost breaker applied."""
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    return await self._post_with_retry(payload, high_priority=is_mistress(user), cmd="raw", user=user)

  async def check_api_models_health(self) -> Tuple[bool, int, str]:
    """Query Google's models endpoint for Angel Diagnostics."""
    url = "https://generativelanguage.googleapis.com/v1beta/models"
    headers = {"x-goog-api-key": self.api_key}
    t0 = time.monotonic()
    try:
      session = await get_shared_http_session()
      async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
          ms = int((time.monotonic() - t0) * 1000)
          if resp.status == 200:
            data = await resp.json()
            cnt = len(data.get("models", []))
            return True, ms, f"متصل بنجاح ({cnt} نموذج متاح)"
          return False, ms, f"HTTP {resp.status}"
    except Exception as exc:
      return False, 0, str(exc)[:80]

  async def generate_angel_reply(
      self,
      user: discord.abc.User,
      summary: Optional[str],
      recent_messages: List[Dict[str, str]],
      user_prompt: str,
      media_items: Optional[List[Tuple[str, str]]] = None,
      harem_title: Optional[str] = None,
      ambient_context: Optional[str] = None,
      pinned_prefs: Optional[str] = None,
      style_mode: str = "realistic",
      knowledge_snippets: Optional[str] = None,
      profile_facts: Optional[List[Dict]] = None,
      cmd: str = "chat",
      culture: Optional[str] = None,
      rhythm_hint: Optional[str] = None,
  ) -> str:
    norm_prompt = normalize_arabic_text(user_prompt or "")
    if (PROBE_PATTERNS.search(user_prompt or "") or PROBE_PATTERNS.search(norm_prompt)) and not is_mistress(user):
      logger.info("ai-guard reason=probe")
      if harem_title:
        return "💖 أنا أنجل يا جميلة، ولستُ برنامجاً أو آلة كما يظنون."
      return "⚡ تسألني عن 'نماذج' و'برمجة'؟ أنا أنجل، ولستُ آلة."

    system_text = build_angel_system_prompt(
        user,
        summary,
        harem_title=harem_title,
        ambient_context=ambient_context,
        pinned_prefs=pinned_prefs,
        style_mode=style_mode,
        knowledge_snippets=knowledge_snippets,
        profile_facts=profile_facts,
        mood=float(getattr(get_bot(), "mood", 0.55)),
        settings=getattr(get_bot(), "settings", None),
        culture=culture,
    )
    if rhythm_hint:
      system_text += "\n" + rhythm_hint
    contents = [
        {
            "role": msg["role"],
            "parts": [{
                "text": (
                    strip_all_control_tags(msg["content"], allow_secret_name=False)
                    if msg["role"] == "model"
                    else msg["content"]
                )
            }],
        }
        for msg in recent_messages
    ]

    user_parts = []
    if media_items:
      for mime_type, b64_data in media_items:
        user_parts.append({"inline_data": {"mime_type": mime_type, "data": b64_data}})
    user_parts.append({"text": user_prompt or "علقي على هذه الصورة باختصار."})
    contents.append({"role": "user", "parts": user_parts})

    payload = {
        "system_instruction": {"parts": [{"text": system_text}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.75, "maxOutputTokens": 900},
    }
    return await self._post_with_retry(
        payload, high_priority=(is_mistress(user) or harem_title is not None),
        cmd=cmd, user=user,
    )

  async def summarize_messages(
      self, old_summary: Optional[str], messages_to_summarize: List[Dict[str, str]]
  ) -> str:
    conversation_text = "\n".join(
        f"{'المتحدث' if m['role'] == 'user' else 'أنجل'}: {m['content']}"
        for m in messages_to_summarize
    )
    prompt = "لخّصي أهم المعلومات والتفاصيل عن هذا الشخص في فقرة قصيرة لتبقى في ذاكرتكِ:\n\n"
    if old_summary:
      prompt += f"الملخص السابق:\n{old_summary}\n\n"
    prompt += f"الرسائل الجديدة:\n{conversation_text}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 600},
    }
    return await self._post_with_retry(payload, high_priority=True, cmd="summary")

  async def summarize_catchup(self, payload_text: str) -> str:
    """Summarise a bounded, pre-sanitised chat log; cost accounting is unchanged."""
    payload = {
        "contents": [{"role": "user", "parts": [{"text": payload_text}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 800},
    }
    return await self._post_with_retry(payload, high_priority=True, cmd="catchup")

  async def custom_prompt(
      self, user: discord.abc.User, prompt_text: str, harem_title: Optional[str] = None, max_tokens: int = 1200
  ) -> str:
    system_text = build_angel_system_prompt(user, None, harem_title=harem_title)
    payload = {
        "system_instruction": {"parts": [{"text": system_text}]},
        "contents": [{"role": "user", "parts": [{"text": prompt_text}]}],
        "generationConfig": {"temperature": 0.35, "maxOutputTokens": max_tokens},
    }
    raw = await self._post_with_retry(payload, high_priority=is_mistress(user), cmd="custom", user=user)
    return strip_all_control_tags(raw)

  async def generate_image_bytes(self, prompt: str, style_Preset: str = "anime") -> Tuple[bytes, str]:
    english_prompt = prompt
    if re.search(r"[\u0600-\u06FF]", prompt):
      try:
        trans_payload = {
            "contents": [{
                "role": "user",
                "parts": [{
                    "text": (
                        "Translate and enhance this image description into a concise English art prompt "
                        "(output ONLY the English prompt, no intro):\n" + prompt
                    )
                }],
            }],
            "generationConfig": {"temperature": 0.35, "maxOutputTokens": 150},
        }
        translated = await self._post_with_retry(trans_payload, high_priority=True, cmd="image-translate")
        if translated:
          english_prompt = strip_all_control_tags(translated).strip('"')
      except Exception:
        pass

    style_suffix = {
        "anime": "anime masterpiece, highly detailed, vibrant lighting, 8k",
        "cinematic": "cinematic dramatic lighting, photorealistic, volumetric shadows, 8k",
        "fantasy": "ethereal dark fantasy art, intricate details, glowing particles, masterpiece",
    }.get(style_Preset, "anime art style, masterpiece, highly detailed, soft lighting")

    full_prompt = f"{english_prompt}, {style_suffix}"
    headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
    timeout_fast = aiohttp.ClientTimeout(total=18)

    session = await get_shared_http_session()
    for img_model in IMAGE_GEN_MODELS:
      endpoint = self._get_endpoint(img_model)
      payload = {
          "contents": [{"role": "user", "parts": [{"text": full_prompt}]}],
          "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
      }
      try:
        async with session.post(endpoint, headers=headers, json=payload, timeout=timeout_fast) as resp:
          if resp.status == 200:
            data = await resp.json()
            candidates = data.get("candidates", [])
            if candidates and "content" in candidates[0]:
              for part in candidates[0]["content"].get("parts", []):
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                  return base64.b64decode(inline["data"]), english_prompt
      except Exception:
        pass

    seed = random.randint(1000, 9999999)
    encoded = urllib.parse.quote(full_prompt)
    fallback_urls = [
        f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&seed={seed}&model=flux&nologo=true",
        f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&seed={seed}&nologo=true",
        f"https://pollinations.ai/p/{encoded}?width=1024&height=1024&seed={seed}&nologo=true",
    ]
    timeout_img = aiohttp.ClientTimeout(total=28)
    for url in fallback_urls:
      try:
        async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout_img) as resp:
          if resp.status == 200:
            img_bytes = await read_bounded_stream(resp, max_bytes=10 * 1024 * 1024, min_bytes=1000)
            if img_bytes:
              cropped_bytes = await remove_bottom_watermark_async(img_bytes)
              _safe_gc_collect()
              return cropped_bytes, english_prompt
      except Exception:
        pass

    raise AIServiceError("تعذر إنشاء الصورة حالياً، حاولي مرة أخرى.")

  async def _http_json(self, url: str, timeout: float = 4.0):
    """GET JSON with the descriptive UA these APIs require (a bare bot UA gets 403)."""
    session = await get_shared_http_session()
    async with session.get(
        url, headers={"User-Agent": GIF_USER_AGENT}, timeout=aiohttp.ClientTimeout(total=timeout)
    ) as resp:
      if resp.status != 200:
        return None
      return await resp.json()

  async def fetch_anime_gif_data(
      self, action: str, for_female_pair: bool = False, allow_romantic: bool = True
  ) -> Tuple[Optional[bytes], Optional[str]]:
    """Fetch an anime reaction GIF.

    Source chain (verified reachable from this host, 2026-11):
      pool (verified URLs from earlier runs) -> nekos.best -> purrbot -> otakugifs
    Tenor / Giphy / boorus / Reddit are key-gated or blocked from this IP, so they
    are no longer used. Harem-only rule: romantic actions are refused before any
    network call for anyone outside mistress+harem.

    For harem requests only sources whose anime title is on `YURI_ANIME_WHITELIST`
    are accepted (nekos.best exposes `anime_name`), so the hidden sapphic engine
    actually picks girl-x-girl art instead of a random reaction.
    """
    clean_action = (action or "").lower().strip()
    if clean_action not in SUPPORTED_GIF_ACTIONS:
      clean_action = ARABIC_GIF_KEYWORDS.get(clean_action, "smug")

    if is_romantic_gif(clean_action) and not allow_romantic:
      logger.info("Romantic GIF '%s' blocked (non-harem member).", clean_action)
      return None, None

    if for_female_pair and clean_action in ("kiss", "hug", "cuddle", "handhold", "cheek_kiss", "peck"):
      clean_action = {
          "kiss": "yuri_kiss", "hug": "yuri_hug", "cuddle": "yuri_cuddle",
          "handhold": "yuri_handhold", "cheek_kiss": "cheek_kiss", "peck": "cheek_kiss",
      }.get(clean_action, clean_action)

    is_sapphic = for_female_pair or clean_action.startswith(("yuri_", "lip_"))
    endpoint = GIF_ACTION_ENDPOINT.get(clean_action, "pat")
    candidate_urls: List[str] = []

    def _is_yuri_title(title: str) -> bool:
      t = (title or "").lower()
      return any(w in t for w in YURI_ANIME_WHITELIST)

    # 1) Verified pool first (instant, already filtered when sapphic).
    if get_bot() is not None:
      try:
        candidate_urls.extend(await get_bot().db.get_random_gif_urls(clean_action, is_sapphic, 6))
      except Exception:
        pass

    # 2) nekos.best: metadata (`anime_name`) lets us enforce the sapphic filter.
    if len(candidate_urls) < 3:
      wanted = 2 if is_sapphic else 1
      for _ in range(wanted):
        data = None
        try:
          data = await self._http_json(f"https://nekos.best/api/v2/{endpoint}?amount=8")
        except Exception:
          data = None
        for item in (data or {}).get("results", []) if isinstance(data, dict) else []:
          url = item.get("url")
          if not url:
            continue
          if is_sapphic and not _is_yuri_title(item.get("anime_name", "")):
            continue
          candidate_urls.append(url)
          if get_bot() is not None:
            try:
              await get_bot().db.add_gif_url(url, clean_action, "nekos.best", is_sapphic)
            except Exception:
              pass
        if len(candidate_urls) >= 6:
          break

    # 3) purrbot: reliable generic fallback (no per-anime metadata).
    if not candidate_urls:
      try:
        data = await self._http_json(f"https://purrbot.site/api/img/sfw/{endpoint}/gif")
        if isinstance(data, dict) and data.get("link"):
          candidate_urls.append(data["link"])
      except Exception:
        pass

    # 4) otakugifs, last resort.
    if not candidate_urls:
      try:
        data = await self._http_json(f"https://api.otakugifs.xyz/gif?reaction={endpoint}")
        if isinstance(data, dict) and data.get("url"):
          candidate_urls.append(data["url"])
      except Exception:
        pass

    if not candidate_urls:
      return None, None

    fresh_urls = [u for u in dict.fromkeys(candidate_urls) if u not in self._recent_gif_urls]
    chosen_pool = fresh_urls if fresh_urls else list(dict.fromkeys(candidate_urls))
    random.shuffle(chosen_pool)

    session = await get_shared_http_session()
    dl_timeout = aiohttp.ClientTimeout(total=3.5)
    for gif_url in chosen_pool[:3]:
      try:
        async with session.get(
            gif_url, headers={"User-Agent": GIF_USER_AGENT}, timeout=dl_timeout
        ) as resp:
          if resp.status == 200:
            gif_bytes = await read_bounded_stream(resp, max_bytes=3 * 1024 * 1024, min_bytes=500)
            if gif_bytes:
              self._recent_gif_urls.append(gif_url)
              return gif_bytes, gif_url
      except Exception:
        continue

    chosen_fallback = chosen_pool[0]
    self._recent_gif_urls.append(chosen_fallback)
    return None, chosen_fallback

  async def extract_profile_facts(self, display_name: str, exchange_text: str) -> List[Dict[str, str]]:
    """Ask the model for 0-3 durable, reusable facts about a member. Returns [] on any doubt."""
    if not exchange_text or len(exchange_text.strip()) < 12:
      return []
    prompt = (
        "استخرج من المحادثة التالية حقائق دائمة ومفيدة عن الشخص (وليس كلاماً عابراً).\n"
        "أرجع JSON فقط بالشكل: {\"facts\":[{\"key\":\"...\",\"value\":\"...\",\"confidence\":0.0}]}\n"
        "الشروط: 0 إلى 3 حقائق كحد أقصى، كل حقيقة قصيرة (أقل من 120 حرفاً)، بلا معلومات حساسة "
        "(كلمات مرور، أرقام هواتف، عناوين، بيانات مالية)، وبلا تخمين.\n"
        f"اسم الشخص: {display_name}\nالمحادثة:\n{exchange_text[:2500]}"
    )
    try:
      raw = await self._post_with_retry(
          {
              "contents": [{"role": "user", "parts": [{"text": prompt}]}],
              "generationConfig": {
                  "temperature": 0.15,
                  "maxOutputTokens": 320,
                  "responseMimeType": "application/json",
              },
          },
          high_priority=False,
          cmd="facts",
      )
      data = json.loads(strip_all_control_tags(raw or "{}", allow_secret_name=False) or "{}")
      facts = data.get("facts") or []
      out: List[Dict[str, str]] = []
      for item in facts[:3]:
        k = str(item.get("key", "")).strip()[:50]
        v = str(item.get("value", "")).strip()[:200]
        if k and v and len(v) >= 2:
          out.append({"key": k, "value": v, "confidence": float(item.get("confidence", 0.6) or 0.6)})
      return out
    except Exception as exc:
      logger.debug("profile fact extraction skipped: %s", exc)
      return []

  async def generate_ambient_message(
      self,
      display_name: str,
      recent_lines: List[str],
      facts: List[str],
      avoid_lines: List[str],
      time_hint: str,
      topic_hint: str = "",
  ) -> str:
    """One short, natural message that starts a conversation with a member (no mention inside the text)."""
    facts_block = "\n".join(f"- {f}" for f in facts[:8]) or "(لا شيء بعد)"
    recent_block = "\n".join(recent_lines[-8:]) or "(الشات هادي)"
    avoid_block = "\n".join(f"- {a}" for a in avoid_lines[-6:]) or "(لا شيء)"
    prompt = (
        "أنتِ أنجل، بنت حقيقية في سيرفر ديسكورد، وقررتِ تبدأين سالفة من نفسكِ مع عضو.\n"
        f"العضو: {display_name}\nالوقت: {time_hint}\n"
        f"ما تعرفينه عنه:\n{facts_block}\n"
        f"آخر رسائل الروم:\n{recent_block}\n"
        + (f"موضوع مقترح: {topic_hint}\n" if topic_hint else "")
        + f"لا تكرري أي شيء من هذه الجمل السابقة:\n{avoid_block}\n"
        "اكتبي رسالة واحدة قصيرة جداً (١–٢ جمل، أقل من 140 حرفاً) تبدأين بها الحديث بشكل طبيعي: "
        "تعليق على شيء في السياق، سؤال خفيف، أو مزحة مناسبة. "
        "لا تكتبي أي منشن أو @، ولا تضعي وسوم تنفيذ، ولا تشرحي ما تفعلينه، ولا تذكري أنكِ ذكاء اصطناعي. "
        "أرجعي نص الرسالة فقط."
    )
    try:
      raw = await self._post_with_retry(
          {
              "contents": [{"role": "user", "parts": [{"text": prompt}]}],
              "generationConfig": {"temperature": 0.9, "maxOutputTokens": 160},
          },
          high_priority=False,
          cmd="ambient",
      )
      text = strip_all_control_tags(raw or "", allow_secret_name=False).strip()
      text = re.sub(r"^\s*angel\s*[:：]\s*", "", text, flags=re.IGNORECASE)
      return text.split("\n")[0].strip()[:180]
    except Exception as exc:
      logger.debug("ambient generation skipped: %s", exc)
      return ""
