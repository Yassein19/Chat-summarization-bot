"""Analyzer: OpenRouter multi-agent (retriever + summarizer) > Groq/OpenAI single-agent > heuristic.
Egyptian-Arabic aware. Never invents facts; marks Unclear when evidence lacking. No PII sent unless key configured."""
import logging
from datetime import datetime, timezone
from .schemas import ConversationAnalysis
from . import config

log = logging.getLogger("wootify.analyzer")

SYSTEM = ("You analyze Arabic/Egyptian-Arabic customer support chats to help the company evaluate its bot. "
  "Analyze in Arabic, output in English. Be evidence-based: quote short evidence, never invent. If unclear, use Unclear. "
  "Classify understanding/response as Good/Partial/Poor/Unclear, sentiment satisfied/dissatisfied/neutral/unclear, resolution resolved/unresolved/unclear. "
  "IMPORTANT: english_summary must be exactly ONE customer-centric sentence: focus on what the CUSTOMER said, wanted, reported, and felt, "
  "plus the final outcome for the customer; mention the bot only briefly as handling context (never summarize bot openers/promotions unless the customer reacted to them).")

def _extract_contact_and_agent(messages, conv_meta=None) -> tuple[str, str, str]:
    """Deterministic extraction (never LLM-invented):
    - customer_name: first customer (message_type 0) sender.name, fallback to conv list meta.
    - mobile: first customer sender.phone_number, fallback to conv list meta / contact_inbox.source_id.
    - agent: unique sender.name for message_type 1 (bot/agent), in order, comma-joined.
    """
    customer_name = ""
    mobile = ""
    for m in messages:
        if m.get("message_type") == 0:
            s = m.get("sender") or {}
            if isinstance(s, dict):
                if not customer_name and s.get("name"):
                    customer_name = s["name"]
                if not mobile and s.get("phone_number"):
                    mobile = s["phone_number"]
                if customer_name and mobile:
                    break
    if isinstance(conv_meta, dict):
        meta_sender = (conv_meta.get("meta") or {}).get("sender") or {}
        if not customer_name and meta_sender.get("name"):
            customer_name = meta_sender["name"]
        if not mobile and meta_sender.get("phone_number"):
            mobile = meta_sender["phone_number"]
    if not mobile:
        # fallback: conversation.contact_inbox.source_id (e.g. "201034999035")
        try:
            for m in messages:
                src = ((m.get("conversation") or {}).get("contact_inbox") or {}).get("source_id")
                if src:
                    mobile = f"+{src}" if not str(src).startswith("+") else str(src)
                    break
        except Exception:
            pass
    agents: list[str] = []
    for m in messages:
        if m.get("message_type") == 1:
            s = m.get("sender") or {}
            name = s.get("name") if isinstance(s, dict) else None
            if name and name not in agents:
                agents.append(name)
    return customer_name, mobile, ", ".join(agents)


def _extract_mobile_and_agent(messages, conv_meta=None) -> tuple[str, str]:
    cname, mobile, agent = _extract_contact_and_agent(messages, conv_meta)
    return mobile, agent

def _heuristic(conv_id, messages, conv_meta=None) -> ConversationAnalysis:
    cust = [m for m in messages if m.get("message_type") == 0 and not m.get("private")]
    bots = [m for m in messages if m.get("message_type") == 1 and not m.get("private")]
    texts = [(m.get("content") or "") for m in messages if m.get("content")]
    # date from earliest
    date = ""
    if messages:
        ts = min(m.get("created_at", 0) for m in messages if isinstance(m.get("created_at"), int))
        if ts: date = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
    first_cust = next((m.get("content","")[:200] for m in cust if m.get("content")), "")
    # repetition: same bot text twice
    btexts = [m.get("content","").strip() for m in bots if m.get("content")]
    rep = "Yes" if len(btexts) != len(set(btexts)) and len(btexts) > 1 else "No"
    ev = " | ".join(t[:120] for t in texts[:3])
    customer_name, mobile, agent = _extract_contact_and_agent(messages, conv_meta)
    # Customer-centric one-sentence summary (heuristic): summarize what the CUSTOMER said,
    # not the bot opener; bot appears only briefly as handling context for evaluation.
    # Strip internal periods to enforce a single trailing period.
    def _one_line(s: str, n: int = 200) -> str:
        s = (s or "").replace("\n", " ").replace("\r", " ").strip()
        s = s.replace(".", " ").replace("。", " ")
        s = " ".join(s.split())
        return s[:n]
    cust_texts = _one_line(" / ".join(m.get("content", "") for m in sorted(cust, key=lambda x: x.get("id", 0)) if m.get("content")), 300) or "no clear customer request"
    # outcome: last customer message if any, else last bot reply (to show how bot left it)
    last_cust = ""
    for m in sorted(cust, key=lambda x: x.get("id", 0), reverse=True):
        if m.get("content"):
            last_cust = _one_line(m.get("content", ""), 120)
            break
    last_bot = ""
    for m in sorted(bots, key=lambda x: x.get("id", 0), reverse=True):
        if m.get("content"):
            last_bot = _one_line(m.get("content", ""), 100)
            break
    who = customer_name or "customer"
    agent_part = agent or "unassigned"
    if last_cust:
        outcome = f"ending with customer saying '{last_cust}'"
    elif last_bot:
        outcome = f"ending with bot replying '{last_bot}'"
    else:
        outcome = "with no reply yet"
    one_sentence = (
        f"Customer {who} ({mobile or 'no phone'}) said: '{cust_texts}' "
        f"({len(cust)} customer messages, handled by {agent_part} with {len(bots)} replies, {outcome})"
    ).strip()
    if not one_sentence.endswith("."):
        one_sentence += "."
    return ConversationAnalysis(
        conversation_id=conv_id, conversation_date=date,
        customer_name=customer_name, mobile_number=mobile, agent_name=agent,
        customer_message_count=len(cust), bot_response_count=len(bots),
        main_intent="(heuristic - needs LLM review)",
        customer_problem=first_cust,
        english_summary=one_sentence,
        chatbot_understanding="Unclear", response_quality="Unclear",
        repetition_detected=rep, incorrect_irrelevant="Unclear",
        customer_sentiment="unclear", resolution_status="unclear",
        main_failure="Needs LLM review",
        evidence=ev[:800],
        recommended_improvement="Configure OPENROUTER_API_KEY (or GROQ_API_KEY) for full Egyptian-Arabic analysis.",
    )

def _chat_json(client, model: str, system: str, user: str) -> dict:
    """One OpenAI-compatible JSON-mode chat call. Raises on failure."""
    import json as _json
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    raw = (resp.choices[0].message.content or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        nl = raw.find("\n")
        if nl != -1:
            raw = raw[nl + 1:]
    data = _json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"model {model} did not return a JSON object")
    return data

def _single_agent_analyze(conv_id, messages, conv_meta, provider) -> ConversationAnalysis:
    last_err: Exception | None = None
    try:
        from openai import OpenAI
        if provider == "groq":
            client = OpenAI(api_key=config.GROQ_API_KEY, base_url=config.GROQ_BASE_URL)
            models = config.groq_model_chain()
        else:
            client = OpenAI(api_key=config.OPENAI_API_KEY)
            models = [config.LLM_MODEL]
        transcript = "\n".join(
            f"[{'CUST' if m.get('message_type')==0 else 'BOT' if m.get('message_type')==1 else 'SYS'}] {(m.get('content') or '')[:500]}"
            for m in messages if m.get("content") and not m.get("private")
        )[:12000]
        schema_hint = (
            "Return ONLY valid JSON with exactly these keys: "
            "main_intent (string, the CUSTOMER's intent), customer_problem (string, what the CUSTOMER reported), "
            "english_summary (string, EXACTLY one customer-centric sentence: what the CUSTOMER said/wanted/felt and the final outcome for the customer; "
            "base it on [CUST] messages, mention [BOT] only briefly as handling context for bot evaluation, never summarize bot openers/promotions unless the customer reacted), "
            "chatbot_understanding (one of Good/Partial/Poor/Unclear), "
            "response_quality (one of Good/Partial/Poor/Unclear), "
            "repetition_detected (Yes/No), incorrect_irrelevant (Yes/No/Unclear), "
            "customer_sentiment (one of satisfied/dissatisfied/neutral/unclear), "
            "resolution_status (one of resolved/unresolved/unclear), "
            "main_failure (string, bot failure if any), evidence (string, short CUSTOMER quotes), "
            "recommended_improvement (string, how the bot should improve). "
            "No markdown, no extra keys."
        )
        system_msg = SYSTEM + " " + schema_hint
        user_msg = f"Conversation {conv_id}:\n{transcript}"
        data = None
        used_model = models[0]
        for model in models:
            try:
                data = _chat_json(client, model, system_msg, user_msg)
                used_model = model
                if model != models[0]:
                    log.info(f"conv {conv_id}: fallback model {model} succeeded")
                break
            except Exception as e:
                last_err = e
                log.warning(f"conv {conv_id}: model {model} failed ({type(e).__name__}), trying next fallback")
                continue
        if data is None:
            raise last_err or RuntimeError("all LLM models failed")
        # normalize enum case (models often capitalize): sentiment/resolution are lowercase literals
        for _k in ("customer_sentiment", "resolution_status"):
            if isinstance(data.get(_k), str):
                data[_k] = data[_k].strip().lower()
        out = ConversationAnalysis(
            conversation_id=conv_id,
            **{k: v for k, v in data.items()
               if k in ConversationAnalysis.model_fields and k not in ("conversation_id", "customer_name", "mobile_number", "agent_name")},
        )
        # Always overwrite with deterministic extraction - never trust LLM for PII
        customer_name, mobile, agent = _extract_contact_and_agent(messages, conv_meta)
        # fill date/counts deterministically too (LLM doesn't set them)
        base = _heuristic(conv_id, messages, conv_meta)
        out.conversation_date = base.conversation_date
        out.customer_message_count = base.customer_message_count
        out.bot_response_count = base.bot_response_count
        out.customer_name = customer_name
        out.mobile_number = mobile
        out.agent_name = agent
        return out
    except Exception as e:
        log.warning(f"LLM ({provider}) failed, heuristic fallback: {e}")
        return _heuristic(conv_id, messages, conv_meta)


# ---- OpenRouter multi-agent: Agent 1 retrieves customer facts, Agent 2 summarizes + evaluates ----
RETRIEVER_SYSTEM = ("You are AGENT 1 (RETRIEVER) for Arabic/Egyptian-Arabic customer support chats. "
  "Read the transcript and extract ONLY customer facts from [CUST] messages. Never summarize the bot, "
  "never invent. If unclear, use empty string. Output English except evidence quotes which stay as said.")

SUMMARIZER_SYSTEM = ("You are AGENT 2 (SUMMARIZER/EVALUATOR) for Arabic/Egyptian-Arabic customer support chats. "
  "You receive the transcript plus Agent 1's retrieved customer facts to help the company evaluate its bot. "
  "Analyze in Arabic, output in English. Evidence-based, never invent; use Unclear when lacking evidence. "
  "english_summary must be EXACTLY ONE customer-centric sentence: what the CUSTOMER said/wanted/felt and the final "
  "outcome for the customer; mention the bot only briefly as handling context, never summarize bot openers/promotions "
  "unless the customer reacted to them.")

def _or_chat(model: str, system: str, user: str) -> dict:
    """One OpenRouter chat call returning a parsed JSON object. Raises on failure."""
    from openai import OpenAI
    import json as _json
    client = OpenAI(api_key=config.OPENROUTER_API_KEY, base_url=config.OPENROUTER_BASE_URL)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.2,
        response_format={"type": "json_object"},
        extra_headers={"HTTP-Referer": config.OPENROUTER_SITE_URL, "X-Title": config.OPENROUTER_APP_TITLE},
    )
    raw = (resp.choices[0].message.content or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        nl = raw.find("\n")
        if nl != -1:
            raw = raw[nl + 1:]
    data = _json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("OpenRouter agent did not return a JSON object")
    return data

def _multi_agent_analyze(conv_id, messages, conv_meta=None) -> ConversationAnalysis:
    """Agent 1 (retriever, fast model) -> Agent 2 (summarizer/evaluator, strong model)."""
    transcript = "\n".join(
        f"[{'CUST' if m.get('message_type')==0 else 'BOT' if m.get('message_type')==1 else 'SYS'}] {(m.get('content') or '')[:500]}"
        for m in messages if m.get("content") and not m.get("private")
    )[:12000]
    # Agent 1: retrieve customer facts
    ret = _or_chat(
        config.OPENROUTER_RETRIEVER_MODEL,
        RETRIEVER_SYSTEM + " Return ONLY valid JSON with exactly: main_intent (CUSTOMER intent), "
        "customer_problem (what CUSTOMER reported), evidence (short CUSTOMER quotes). No markdown, no extra keys.",
        f"Conversation {conv_id}:\n{transcript}",
    )
    # Agent 2: summarize + evaluate, grounded on Agent 1 output
    import json as _json
    summ = _or_chat(
        config.OPENROUTER_SUMMARIZER_MODEL,
        SUMMARIZER_SYSTEM + " Return ONLY valid JSON with exactly: english_summary (EXACTLY one customer-centric sentence), "
        "chatbot_understanding (Good/Partial/Poor/Unclear), response_quality (Good/Partial/Poor/Unclear), "
        "repetition_detected (Yes/No), incorrect_irrelevant (Yes/No/Unclear), "
        "customer_sentiment (satisfied/dissatisfied/neutral/unclear), resolution_status (resolved/unresolved/unclear), "
        "main_failure (bot failure if any), recommended_improvement (how the bot should improve). No markdown, no extra keys.",
        f"Conversation {conv_id}:\n{transcript}\n\nAgent1 retrieved facts:\n{_json.dumps(ret, ensure_ascii=False)[:3000]}",
    )
    merged = {**{k: ret.get(k) for k in ("main_intent", "customer_problem", "evidence") if ret.get(k) is not None},
              **{k: summ.get(k) for k in ("english_summary", "chatbot_understanding", "response_quality",
                  "repetition_detected", "incorrect_irrelevant", "customer_sentiment",
                  "resolution_status", "main_failure", "recommended_improvement") if summ.get(k) is not None}}
    for _k in ("customer_sentiment", "resolution_status"):
        if isinstance(merged.get(_k), str):
            merged[_k] = merged[_k].strip().lower()
    out = ConversationAnalysis(
        conversation_id=conv_id,
        **{k: v for k, v in merged.items()
           if k in ConversationAnalysis.model_fields and k not in ("conversation_id", "customer_name", "mobile_number", "agent_name")},
    )
    customer_name, mobile, agent = _extract_contact_and_agent(messages, conv_meta)
    base = _heuristic(conv_id, messages, conv_meta)
    out.conversation_date = base.conversation_date
    out.customer_message_count = base.customer_message_count
    out.bot_response_count = base.bot_response_count
    out.customer_name = customer_name
    out.mobile_number = mobile
    out.agent_name = agent
    return out

def analyze(conv_id, messages, conv_meta=None) -> ConversationAnalysis:
    provider = config.llm_provider()
    if provider == "none":
        return _heuristic(conv_id, messages, conv_meta)
    if provider == "openrouter":
        try:
            return _multi_agent_analyze(conv_id, messages, conv_meta)
        except Exception as e:
            log.warning(f"OpenRouter multi-agent failed, heuristic fallback: {e}")
            return _heuristic(conv_id, messages, conv_meta)
    return _single_agent_analyze(conv_id, messages, conv_meta, provider)
