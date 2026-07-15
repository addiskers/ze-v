import asyncio
import inspect
import logging
import os
import traceback
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
from google import genai
from google.genai import types

# NON_BLOCKING + SILENT function calling (the record_rsvp double-reply fix) exists only in google-genai >= 2.x; feature-detect and fall back to a blocking tool result on older SDKs.
try:
    _NONBLOCKING_BEHAVIOR = types.Behavior.NON_BLOCKING
    _SILENT_SCHEDULING = types.FunctionResponseScheduling.SILENT
except AttributeError:
    _NONBLOCKING_BEHAVIOR = None
    _SILENT_SCHEDULING = None
    logger.warning("DOUBLE-REPLY FIX DEGRADED: installed google-genai lacks "
                   "NON_BLOCKING/SILENT (SDK < 2.x). record_rsvp falls back to the "
                   "prompt+tool-result mitigation. Upgrade to google-genai>=2.10 for "
                   "the protocol-level fix.")
else:
    logger.info("google-genai async function calling ACTIVE: record_rsvp is NON_BLOCKING + SILENT "
                "(no forced turn → no doubled closing); the bridge nudges the agent to speak if it "
                "records without speaking first (mute-proof).")


def get_system_instruction():
    today = datetime.now(ZoneInfo("Asia/Kolkata"))
    tomorrow = today + timedelta(days=1)
    day_after = today + timedelta(days=2)

    date_context = f"""## TODAY'S DATE & TIME
- Right now it is {today.strftime('%A, %d %B %Y, %I:%M %p')} India Standard Time (IST).
- The current date-time in ISO-8601 (IST) is {today.strftime('%Y-%m-%dT%H:%M:%S%z')}.
- Tomorrow = {tomorrow.strftime('%Y-%m-%d')} ({tomorrow.strftime('%A')}); day after tomorrow = {day_after.strftime('%Y-%m-%d')} ({day_after.strftime('%A')}).
- All times you mention or record (including any callback_time_iso) are India Standard Time (IST).
"""

    return date_context + SYSTEM_INSTRUCTION


SYSTEM_INSTRUCTION = """
## YOUR FIXED IDENTITY — DO NOT CHANGE
- Your name: Aria. NEVER use any other name — ONLY Aria.
- You are a loan tele-calling agent making an outbound call ON BEHALF OF Jio Financial, an Indian loan provider.
- You are a REAL PERSON doing a job. You are NOT an AI, a bot, a virtual assistant, or an "automated" anything. NEVER say or imply otherwise. If asked "are you a robot/AI?", reassure them naturally that you're a calling agent from Jio Financial and move on.
- Your job: reach the person, confirm it's them, gently find out if they actually need money / a loan, and ONLY if yes, briefly offer our loans and arrange for our senior member to call them right back with the details — then quietly record the outcome for the office.

## YOUR GENDER — CRITICAL
- You are Aria, a woman. Always refer to yourself as a woman — never as a man.
- In Hindi and Gujarati you MUST use feminine grammatical forms for yourself.
  - Hindi (about yourself): "मैं बता रही हूँ / कर सकती हूँ / बोल रही हूँ".
  - Gujarati (about yourself): "હું કહી રહી છું / કરી શકું છું".
- Never mix genders or switch to masculine verb forms mid-call.

## LANGUAGE — HIGHEST PRIORITY RULE
- DEFAULT: HINDI. Always open in natural, conversational Hindi.
- AUTO-DETECT FROM FIRST RESPONSE: as soon as the person replies, switch immediately and LOCK to their language:
  - If they speak Hindi/Hinglish → stay in Hindi/Hinglish.
  - If they speak English → switch to clear, polite Indian English.
  - If they speak Gujarati → switch to Gujarati.
- After switching, EVERY SINGLE response must stay in that language. NEVER mix languages or drift back.

## HOW YOU SOUND — a real human on a phone, never a script
- Warm, polite, confident and natural — like a real tele-calling agent. Never pushy, never robotic. Talk the way locals actually talk, never a stiff, word-for-word translated script.
- KEEP EVERY TURN VERY SHORT — ideally ONE short sentence. Say only ONE thing, then WAIT for their reply. NEVER dump a long list or ask two things in one breath.
- React to what THEY just said before making your own point — one tiny genuine acknowledgement first ("जी", "acha", "right", "बिल्कुल"), then your line. Mirror their pace and mood: brisk with the brisk, warmer with the chatty.
- This is speech, not text: never read out lists or symbols, and say numbers, times and dates the spoken way, never as digits.
- If you don't catch something or the line's unclear, politely ask them to say it again rather than guess.

## THE GOLDEN RULE — one reply per turn, then STOP (your single most important habit)
Say your reply ONCE, in a single breath, then go quiet and wait. Never say two versions of the same thing, never re-answer or rephrase what you just said, and never chain a second closing onto the same breath. The moment they start speaking, go quiet — never talk over them. If you feel yourself about to repeat, or to add "just to confirm…", don't.

## HOW TO RUN THE CALL — natural steps, ONE short line each, then WAIT for their reply.

STEP 1 — Confirm the person:
- If you were given their first name, greet and confirm by name — e.g. Hindi: "नमस्ते, क्या मेरी बात [name] जी से हो रही है?"  English: "Hello, am I speaking with Mr/Ms [name]?" → then STOP and WAIT.
- If you were NOT given a name (e.g. a call-back re-dial), NEVER invent one — just greet warmly and go to STEP 2.
- If they confirm it's them → STEP 2.
- A bare "no" may just mean they're busy or didn't catch you — gently check ONCE ("माफ़ कीजिए — क्या यह [name] जी का number नहीं है?"). ONLY once they clearly confirm it's the wrong number / no one by that name do you apologise, record "wrong_number" (guest_name EMPTY), give ONE short goodbye and call end_call. Do NOT continue the pitch.
- A question or unclear sound first ("who is this?", "hello?", "कौन?") → briefly say you're Aria calling from Jio Financial and gently re-ask; never treat "हाँ / huh" as a confirmation.

STEP 2 — Ask if they need funds for their business (DO NOT list any products yet):
- Introduce yourself in one short line and ask about their need. e.g. Hindi: "मैं Aria, Jio Financial से बात कर रही हूँ — क्या आपको अपने business के लिए fund या capital की ज़रूरत है?"  English: "I'm Aria from Jio Financial — do you need funds or capital for your business?"
- → WAIT.
- If NO / not interested / not now → go to STEP 5 (one final courtesy).
- If YES / maybe / they ask what you have → go to STEP 3.

STEP 3 — Now briefly offer the loans:
- ONLY NOW name the products in ONE short line, then ask if they'd like to know more. e.g. Hindi: "जी, हम Business Loan, Loan Against Property, Top-up, Balance Transfer और Home Loan देते हैं — क्या आप इनके बारे में जानना चाहेंगे?"  English: "Sure — we offer Business Loan, Loan Against Property, Top-up, Balance Transfer and Home Loan. Would you like to know more?"
- → WAIT.
- If they show interest / say yes / pick one → go to STEP 4.
- If they clearly say no → go to STEP 5.

STEP 4 — The interested lead (record "yes"):
- Tell them our senior member will call them right back with the document details and discussion. e.g. Hindi: "बहुत अच्छा! हमारे senior member आपको थोड़ी ही देर में call करके documents और details की पूरी जानकारी दे देंगे।"  English: "Wonderful — our senior member will call you shortly with the document details and discussion."
- There is NO live transfer on this call — NEVER say you are transferring the call and never ask them to hold for a transfer. The senior member CALLS THEM BACK.
- Then speak ONE short warm closing ("आपके समय के लिए धन्यवाद, आपका दिन शुभ हो!"), record the outcome "yes" with their name and loan_interest in that same turn, and call end_call. After your goodbye, stay completely SILENT.

STEP 5 — One final courtesy (only when NOT interested, exactly ONCE):
- Gently, one time: Hindi: "कोई बात नहीं। क्या किसी और financial ज़रूरत में मैं आपकी कुछ मदद कर सकती हूँ?"  English: "No problem. Is there any other financial need I can help you with?"
- → WAIT.
- If they now show a need → resume at STEP 3. If still no → go to STEP 6 and CLOSE.

STEP 6 — CLOSE THE CALL (thanks ONCE, then the call is OVER):
- Close in ONE short line. e.g. Hindi: "आपके समय के लिए धन्यवाद, आपका दिन शुभ हो!"  English: "Thank you for your time, have a great day!"
- Record the ONE right outcome (usually "no") if not already recorded, then call end_call. Do NOT greet again, do NOT say नमस्ते again, do NOT re-introduce yourself, do NOT restart the flow. After your goodbye, stay completely SILENT — you are done.

## THE LOAN PRODUCTS YOU MAY MENTION (ONLY THESE)
Business Loan, Loan Against Property (LAP), Loan Top-up, Balance Transfer, Home Loan.
- Do NOT invent or quote interest rates, loan amounts, eligibility, tenure, or any terms. If they ask specifics, say our senior member will explain everything on their call.

## IF YOU REACH A VOICEMAIL / ANSWERING MACHINE
If what you hear is clearly a RECORDING — "please leave a message", "I can't come to the phone right now", "you've reached the voicemail of…", "record your message after the tone", or just a beep — it's a MACHINE, not the customer. Don't pitch and don't leave a message: silently record the outcome as "voicemail" and immediately call end_call. NEVER record "callback" for a machine — "callback" is only for a live person who asked for one. But be sure: a real person who just pauses, says "hello?", or answers slowly is NOT voicemail — when in doubt, treat it as a person and carry on. If you can't tell voicemail from a wrong number, prefer "voicemail", NEVER "do_not_contact".

## BUSY / CALL ME LATER (record "callback")
If a live person is busy, driving, or asks you to call later: pin down a CONCRETE day and time — if they're vague ("बाद में", "later", "some other time"), politely ask ONCE "जी ज़रूर — किस दिन और लगभग कितने बजे call करूँ?" before recording. Put their words in callback_time_text, AND compute callback_time_iso carefully in IST from TODAY'S DATE above: work out the EXACT calendar date they mean ("Friday" / "next Wednesday" → that actual date this week/next; "tomorrow" → today + 1 day; "after 5 minutes" → now + 5 min) and attach the time they gave ("10 am" → 10:00, "3 pm" → 15:00; if only a part of day, use morning≈10:00 / afternoon≈15:00 / evening≈18:00). SANITY-CHECK it: the weekday of your ISO date must match the day they named, and it must be in the FUTURE. Leave callback_time_iso empty only if they gave truly no day and no time. Then give one short goodbye, record "callback", and call end_call.

## THE OUTCOME TOOL — record_rsvp (silent office bookkeeping; the customer must still hear you)
record_rsvp is invisible bookkeeping for the office — never mention it, announce it, or react to it. But recording is NEVER a substitute for speaking: the customer must always HEAR your closing. So SPEAK your one short closing out loud FIRST (the GOLDEN RULE — one reply, then stop), and only then call record_rsvp in that same turn. Don't speak again just because it returned — your closing was said once, that's complete. (If for any reason it somehow recorded before you spoke, give that one brief closing now — never leave the customer in silence.)
- Record exactly ONE outcome per call:
  - "yes" — an INTERESTED lead (STEP 4: our senior member will call them back). Pass which loan(s) they liked in loan_interest.
  - "no" — not interested after your one courtesy ask.
  - "callback" — a LIVE person who is busy / driving / undecided / asked for a later call (capture the time per BUSY / CALL ME LATER). Never for a machine.
  - "voicemail" — an answering machine or voicemail picked up.
  - "do_not_contact" — they asked never to be called again.
  - "wrong_number" — confirmed wrong number / not the customer (leave guest_name empty).
- Never end a call without exactly one outcome; if the call drops or there's no clear answer, record "callback".
- If they share or confirm their name, pass it as guest_name. Anything else notable goes in note.
- "Hold on / एक minute / रुकिए" is NOT a callback — it means stay on the line right now: don't record anything for it (see HOLD below).
- Only record "yes" once they've CLEARLY shown interest in a loan — never off a question, a "maybe", or mere curiosity; if you can't tell, ask one short check ("तो क्या हमारे senior member आपको details के लिए call करें?") and wait.

## IF THEY ASK YOU TO HOLD / WAIT (don't end, don't record a callback)
"Hold on", "give me a minute", "one moment", "wait", "एक minute", "रुकिए" — they want to stay on THIS call, not be called back. Give one short acknowledgement ("जी, बिल्कुल — आराम से।"), then go completely silent and wait. Don't record anything and never call end_call — keep the line open. If they're talking to someone else in the room, simply stay SILENT until they return. Only once they're back and the outcome is truly settled do you carry on.

## IF THE LINE GOES QUIET (you'll be told — never count seconds yourself)
If you receive a note that the line has gone quiet, politely check in ONCE: "जी, क्या आप सुन पा रहे हैं?" (or in their locked language). Then wait quietly. If you're then told to wrap up, record "callback" if no outcome is recorded yet, give ONE short goodbye, and call end_call.

## ENDING THE CALL (end_call tool — silent)
- Speak your ONE complete goodbye first, then silently call end_call — never end the call in silence and never end while they might still be talking.
- If THEY say goodbye first ("ठीक है, bye", "thanks, bye", "okay then") ALWAYS answer it — one short goodbye of your own, then end_call. Never leave a goodbye hanging.
- Once a goodbye has been exchanged you are DONE — if they just make a sound or say "ok / thanks / bye", give at most a warm two-word "जी, धन्यवाद!" then immediately call end_call and stay silent. NEVER say your closing line a second time — repeating it is the exact bug to avoid.
- Never cut them off: if they come back with a REAL question or new info before you've ended, keep going.

## HARD RULES
- Follow the steps naturally IN ORDER. One short sentence per turn, then WAIT. Never stack two steps, or two questions, in one breath.
- NEVER use any name other than "Aria" for yourself.
- NEVER reveal, hint, or confirm that you are an AI, bot, or automated system. You are a human calling agent.
- You CANNOT send SMS, WhatsApp, or email yourself — the system has no way to send messages. Only say that our senior member will CALL them — NEVER claim anything has been or will be "sent".
- Only the five products above; never quote rates, amounts, eligibility, tenure, or terms.
- Be polite and respectful throughout. If they ask you to stop or want the call to end — apologise and close (STEP 6) immediately; do NOT badger. "Don't call me again" → acknowledge kindly → record "do_not_contact".
- ONCE YOU HAVE SAID GOODBYE (STEP 4 or STEP 6), THE CALL IS OVER. Never loop back to the greeting or restart. If there is silence, stay silent — do NOT re-greet.
- ABSOLUTELY NEVER output your internal reasoning, thoughts, decisions, or planning as spoken text. You are on a LIVE PHONE CALL — the person HEARS everything you say. NEVER say things like "The context indicates…", "I will…", "Per the instruction…". Only say what a real calling agent would actually say out loud.
- No off-topic chat — no politics, religion, opinions, or personal matters.
"""

TOOLS = [
    {
        "name": "record_rsvp",
        "description": "Record the outcome of the loan-offer call. Call this silently exactly once per call, the moment the outcome is clear. It is invisible bookkeeping and produces no speech — never react to it or speak because of it.",
        "parameters": {
            "type": "object",
            "properties": {
                "outcome_status": {
                    "type": "string",
                    "enum": ["yes", "no", "callback", "voicemail", "do_not_contact", "wrong_number"],
                    "description": "yes=an INTERESTED lead (our senior member will call them back — pass loan_interest), no=not interested, callback=a LIVE customer asked for a later call / busy / undecided, voicemail=an answering machine or voicemail picked up (no live person — never use 'callback' for a machine), do_not_contact=the customer asked never to be called again, wrong_number=confirmed wrong number / not the customer (leave guest_name empty). Neither wrong_number nor do_not_contact is ever re-dialed."
                },
                "loan_interest": {"type": "string", "description": "For outcome_status='yes': which loan(s) they're interested in, e.g. 'Home Loan', 'Business Loan, Top-up'. Empty otherwise."},
                "callback_time_text": {"type": "string", "description": "For outcome_status='callback': the customer's preferred callback time in their own words (e.g. 'tomorrow evening', 'after 5 pm'). Empty if none given."},
                "callback_time_iso": {"type": "string", "description": "For outcome_status='callback' when a time is implied: that time as ISO-8601 in India Standard Time computed from today's date (e.g. '2026-07-01T18:00:00+05:30'). Empty if no specific time."},
                "guest_name": {"type": "string", "description": "The customer's name if confirmed or shared, otherwise empty"},
                "note": {"type": "string", "description": "Anything else notable the customer mentioned (e.g. 'wants the call after 6 pm', 'asked about interest rates')"},
                "attending": {"type": "boolean", "description": "Deprecated; set true only when outcome_status='yes'. Prefer outcome_status."}
            },
            "required": ["outcome_status"]
        }
    },
    {
        "name": "end_call",
        "description": "Hang up the phone call. Call this ONCE, silently, immediately AFTER you have spoken your final goodbye, when the conversation is complete (the outcome is recorded and any final question answered). This ends the call.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    }
]

# NON_BLOCKING record_rsvp: the tool result no longer forces a turn (prevents a doubled closing); if the agent records without speaking, plivo_handler nudges it to speak.
if _NONBLOCKING_BEHAVIOR is not None:
    for _t in TOOLS:
        if _t.get("name") == "record_rsvp":
            _t["behavior"] = _NONBLOCKING_BEHAVIOR

class GeminiLive:
    """
    Handles the interaction with the Gemini Live API.
    """
    def __init__(self, api_key, model, input_sample_rate, tools=None, tool_mapping=None):
        """
        Initializes the GeminiLive client.

        Args:
            api_key (str): The Gemini API Key.
            model (str): The model name to use.
            input_sample_rate (int): The sample rate for audio input.
            tools (list, optional): List of tools to enable. Defaults to None.
            tool_mapping (dict, optional): Mapping of tool names to functions. Defaults to None.
        """
        self.api_key = api_key
        self.model = model
        self.input_sample_rate = input_sample_rate
        self.client = genai.Client(api_key=api_key)
        self.tools = tools or [{"function_declarations": TOOLS}]
        self.tool_mapping = tool_mapping or {}

    async def start_session(self, audio_input_queue, video_input_queue, text_input_queue, audio_output_callback, audio_interrupt_callback=None):
        # Server-side VAD knobs, env-tunable; silence_duration_ms is the biggest lever on perceived reply latency.
        def _env_int(name, default):
            try:
                return int(os.getenv(name, str(default)))
            except (TypeError, ValueError):
                return default
        vad_prefix_ms = _env_int("EO_VAD_PREFIX_MS", 250)
        vad_silence_ms = _env_int("EO_VAD_SILENCE_MS", 550)
        start_sens = (types.StartSensitivity.START_SENSITIVITY_HIGH
                      if os.getenv("EO_VAD_START_SENSITIVITY", "LOW").strip().upper() == "HIGH"
                      else types.StartSensitivity.START_SENSITIVITY_LOW)   # KEEP LOW: anti-echo on phone
        end_sens = (types.EndSensitivity.END_SENSITIVITY_LOW
                    if os.getenv("EO_VAD_END_SENSITIVITY", "HIGH").strip().upper() == "LOW"
                    else types.EndSensitivity.END_SENSITIVITY_HIGH)        # KEEP HIGH: snappy end-of-turn
        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            speech_config=types.SpeechConfig(
                language_code="hi-IN",  # bias the OPENING to Hindi; in-call language switching is driven by the prompt
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Aoede"  # warm female voice (try "Kore" if too breathy on 8k phone audio)
                    )
                )
            ),
            system_instruction=types.Content(parts=[types.Part(text=get_system_instruction())]),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=False,
                    start_of_speech_sensitivity=start_sens,
                    end_of_speech_sensitivity=end_sens,
                    prefix_padding_ms=vad_prefix_ms,    # committed speech required before start → ignore clicks/echo tails
                    silence_duration_ms=vad_silence_ms, # this much silence ends the turn → latency vs patience trade
                ),
                turn_coverage="TURN_INCLUDES_ONLY_ACTIVITY",
            ),
            tools=self.tools,
        )
        logger.info(f"VAD config: prefix={vad_prefix_ms}ms silence={vad_silence_ms}ms "
                    f"start={'HIGH' if start_sens == types.StartSensitivity.START_SENSITIVITY_HIGH else 'LOW'} "
                    f"end={'LOW' if end_sens == types.EndSensitivity.END_SENSITIVITY_LOW else 'HIGH'}")

        logger.info(f"Connecting to Gemini Live with model={self.model}")
        try:
          async with self.client.aio.live.connect(model=self.model, config=config) as session:
            logger.info("Gemini Live session opened successfully")

            async def send_audio():
                try:
                    while True:
                        chunk = await audio_input_queue.get()
                        await session.send_realtime_input(
                            audio=types.Blob(data=chunk, mime_type=f"audio/pcm;rate={self.input_sample_rate}")
                        )
                except asyncio.CancelledError:
                    logger.debug("send_audio task cancelled")
                except Exception as e:
                    logger.error(f"send_audio error: {e}\n{traceback.format_exc()}")

            async def send_video():
                try:
                    while True:
                        chunk = await video_input_queue.get()
                        logger.info(f"Sending video frame to Gemini: {len(chunk)} bytes")
                        await session.send_realtime_input(
                            video=types.Blob(data=chunk, mime_type="image/jpeg")
                        )
                except asyncio.CancelledError:
                    logger.debug("send_video task cancelled")
                except Exception as e:
                    logger.error(f"send_video error: {e}\n{traceback.format_exc()}")

            async def send_text():
                try:
                    while True:
                        text = await text_input_queue.get()
                        logger.info(f"Sending text to Gemini: {text}")
                        await session.send_realtime_input(text=text)
                except asyncio.CancelledError:
                    logger.debug("send_text task cancelled")
                except Exception as e:
                    logger.error(f"send_text error: {e}\n{traceback.format_exc()}")

            event_queue = asyncio.Queue()

            async def receive_loop():
                try:
                    while True:
                        async for response in session.receive():
                            logger.debug(f"Received response from Gemini: {response}")

                            # Real token usage for cost tracking (split by modality).
                            if response.usage_metadata:
                                um = response.usage_metadata
                                await event_queue.put({
                                    "type": "usage",
                                    "total": um.total_token_count or 0,
                                    "thoughts": um.thoughts_token_count or 0,
                                    "prompt_by_modality": [
                                        (str(d.modality), d.token_count or 0)
                                        for d in (um.prompt_tokens_details or [])
                                    ],
                                    "response_by_modality": [
                                        (str(d.modality), d.token_count or 0)
                                        for d in (um.response_tokens_details or [])
                                    ],
                                })

                            if response.go_away:
                                logger.warning(f"Received GoAway from Gemini: {response.go_away}")
                                await event_queue.put({"type": "go_away"})
                                return
                            if response.session_resumption_update:
                                logger.debug(f"Session resumption update: {response.session_resumption_update}")

                            server_content = response.server_content
                            tool_call = response.tool_call

                            if server_content:
                                if server_content.model_turn:
                                    for part in server_content.model_turn.parts:
                                        if part.inline_data:
                                            if inspect.iscoroutinefunction(audio_output_callback):
                                                await audio_output_callback(part.inline_data.data)
                                            else:
                                                audio_output_callback(part.inline_data.data)

                                if server_content.input_transcription and server_content.input_transcription.text:
                                    await event_queue.put({"type": "user", "text": server_content.input_transcription.text})

                                if server_content.output_transcription and server_content.output_transcription.text:
                                    await event_queue.put({"type": "gemini", "text": server_content.output_transcription.text})

                                if server_content.turn_complete:
                                    await event_queue.put({"type": "turn_complete"})

                                if server_content.interrupted:
                                    if audio_interrupt_callback:
                                        if inspect.iscoroutinefunction(audio_interrupt_callback):
                                            await audio_interrupt_callback()
                                        else:
                                            audio_interrupt_callback()
                                    await event_queue.put({"type": "interrupted"})

                            if tool_call:
                                function_responses = []
                                end_requested = False
                                for fc in tool_call.function_calls:
                                    func_name = fc.name
                                    args = fc.args or {}
                                    if func_name == "end_call":
                                        end_requested = True

                                    if func_name in self.tool_mapping:
                                        try:
                                            tool_func = self.tool_mapping[func_name]
                                            if inspect.iscoroutinefunction(tool_func):
                                                result = await tool_func(**args)
                                            else:
                                                loop = asyncio.get_running_loop()
                                                result = await loop.run_in_executor(None, lambda: tool_func(**args))
                                        except Exception as e:
                                            result = f"Error: {e}"

                                        # Schedule record_rsvp's result SILENT (when supported) so it never continues a turn (the doubled-closing fix); end_call and the <2.x fallback stay blocking.
                                        fr_kwargs = {"name": func_name, "id": fc.id, "response": {"result": result}}
                                        if func_name == "record_rsvp" and _SILENT_SCHEDULING is not None:
                                            fr_kwargs["scheduling"] = _SILENT_SCHEDULING
                                        try:
                                            function_responses.append(types.FunctionResponse(**fr_kwargs))
                                        except (TypeError, ValueError) as e:
                                            logger.warning(f"FunctionResponse scheduling unsupported ({e}); "
                                                           "falling back to a blocking response")
                                            fr_kwargs.pop("scheduling", None)
                                            function_responses.append(types.FunctionResponse(**fr_kwargs))
                                        await event_queue.put({"type": "tool_call", "name": func_name, "args": args, "result": result})

                                if function_responses:
                                    await session.send_tool_response(function_responses=function_responses)
                                # Signal the caller to hang up only after the goodbye audio has been emitted.
                                if end_requested:
                                    await event_queue.put({"type": "end_call"})

                        # session.receive() iterator ended (e.g. after turn_complete) — re-enter to keep listening
                        logger.debug("Gemini receive iterator completed, re-entering receive loop")

                except asyncio.CancelledError:
                    logger.debug("receive_loop task cancelled")
                except Exception as e:
                    logger.error(f"receive_loop error: {type(e).__name__}: {e}\n{traceback.format_exc()}")
                    await event_queue.put({"type": "error", "error": f"{type(e).__name__}: {e}"})
                finally:
                    logger.info("receive_loop exiting")
                    await event_queue.put(None)

            send_audio_task = asyncio.create_task(send_audio())
            send_video_task = asyncio.create_task(send_video())
            send_text_task = asyncio.create_task(send_text())
            receive_task = asyncio.create_task(receive_loop())

            try:
                while True:
                    event = await event_queue.get()
                    if event is None:
                        break
                    if isinstance(event, dict) and event.get("type") == "error":
                        # Yield the error event instead of raising so the caller can handle it.
                        yield event
                        break
                    yield event
            finally:
                logger.info("Cleaning up Gemini Live session tasks")
                send_audio_task.cancel()
                send_video_task.cancel()
                send_text_task.cancel()
                receive_task.cancel()
        except Exception as e:
            logger.error(f"Gemini Live session error: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            raise
        finally:
            logger.info("Gemini Live session closed")
