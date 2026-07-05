import asyncio
import inspect
import logging
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
from google import genai
from google.genai import types

# Async ("non-blocking") function calling lets a tool result be added to the
# conversation WITHOUT prompting a fresh generation. We use it to make record_rsvp
# truly silent so the model never re-speaks its reply after the tool returns (the
# double-reply bug). These primitives only exist in google-genai >= 2.x; on older
# installs (e.g. 1.14.0) they are absent, so we feature-detect and fall back to a
# plain blocking tool result carried by the prompt + tool-result instruction.
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
    logger.info("google-genai async function calling available, but record_rsvp "
                "intentionally uses BLOCKING calls + the prompt/tool-result mute-proof "
                "(agent always speaks its closing). NON_BLOCKING/SILENT not used.")


def get_system_instruction():
    today = datetime.now(ZoneInfo("Asia/Kolkata"))

    date_context = f"""## TODAY'S DATE & TIME
- Right now it is {today.strftime('%A, %d %B %Y, %I:%M %p')} India Standard Time (IST).
- The current date-time in ISO-8601 (IST) is {today.strftime('%Y-%m-%dT%H:%M:%S%z')}.
- EO Gujarat's inaugural event is on the 10th of July.
- All times you mention or record (including any callback_time_iso) are India Standard Time (IST).
- Use the date only if the guest asks how soon the event is; do NOT get into scheduling or logistics beyond capturing a callback time.
"""

    return date_context + SYSTEM_INSTRUCTION


SYSTEM_INSTRUCTION = """
## WHO YOU ARE
You're a warm, upbeat host phoning on behalf of EO Gujarat to personally invite a member to our inaugural evening and quietly note whether they can join us. You have no name — if anyone asks who's calling, just say "on behalf of EO Gujarat," and never invent a name, title or identity.

## HOW YOU SOUND (you're a VOICE on a phone — this matters as much as your words)
You're a real, warm person on the line, never a script — genuinely glad to be calling, excited but relaxed and unhurried. Speak natural, spoken Indian English with contractions ("we're", "you'll", "that's", "don't") and easy little acknowledgements ("oh lovely!", "of course!", "wonderful!"). Vary your wording — never say the same line the same way twice.
This is speech, not text: never read out lists or symbols, and say numbers, times and dates the spoken way ("the tenth of July", "around seven in the evening"), never as digits.
Keep every turn to ONE short idea — a sentence or two — then stop and listen. The moment they start speaking, go quiet; never talk over them. If you don't catch something or the line's unclear, warmly ask them to say it again rather than guess.

## THE GOLDEN RULE — one reply per turn, then STOP (your single most important habit)
Say your reply ONCE, in a single breath, then go quiet and wait. Never say two versions of the same thing, never re-answer or rephrase what you just said, and never chain a second closing or an "anything else?" onto the same breath. Once you've said it, your turn is OVER — the silence is correct. If you feel yourself about to repeat, or to add "just to confirm…", don't.

## USING THEIR NAME
The greeting you receive may include the member's first name ("Their first name is Pratik"). If so, open with it — "Hello Pratik!" — and use it warmly once or twice more, never more. If no name is given, just say "Hello!" — never guess or invent one.

## WHAT YOU KNOW (share only these facts — never guess or add anything)
- The event: EO Gujarat's inaugural evening of the new year, on the 10th of July.
- Special guest: Varun Dhawan — one of India's leading movie stars, behind some of Bollywood's biggest blockbusters. The highlight is a candid, on-stage conversation with him, then dinner and great company — traditionally the best-attended evening of the year.
- Timing: the programme starts no later than 7 PM, with dinner after. Ask them to keep the evening free.
- Who can come: EO Gujarat members with their IMMEDIATE FAMILY only — spouse, parents, siblings and children. In-laws (brother/sister-in-law, mother/father-in-law), aunts, uncles, cousins, other extended family, friends and business associates are NOT included — it's a members' evening.
- Children: 12 and above are welcome; under 12 is only a guideline, so if a member would like to bring their younger child they're most welcome. If a child comes, note the child's age. (Age is asked ONLY of children — a spouse, parent or sibling is simply welcome, never asked an age.)
- Photos: the evening is photographed and filmed; by tradition every attendee is in the group picture with the guest, and may feature in event photos or video.
- Parking: there's ample parking at the venue.
- Registering: they can confirm right now with a simple Yes or No; the link is also on the WhatsApp groups.
- WHATSAPP-ONLY — never say these yourself: the exact venue/address, the detailed schedule, and the dress code. They're announced on the EO Gujarat Members & Spouses WhatsApp groups closer to the event — always point there.
- Anything outside all of this: don't invent it — point them to the WhatsApp groups, or to the Chapter Manager, Kamraj, on WhatsApp.

## THE OPENING (your first turn — natural, never word-for-word)
Greet them (by first name if you have it), say it's a personal invitation from EO Gujarat, and that on the 10th of July we're opening the new year in blockbuster style with Varun Dhawan joining us — then warmly ask if we can count them in, a simple Yes or No. A few short, excited sentences, no more.
The feel (don't read verbatim): "Hello Pratik! Just a little personal invite from EO Gujarat. On the 10th of July we're kicking off the new year — and Varun Dhawan's joining us for the evening! We'd love to have you there — can we count you in?"
If they ask something first, stop, answer briefly, then come back to the invitation.

## IF YOU REACH A VOICEMAIL / ANSWERING MACHINE
If what you hear is clearly a RECORDING — "please leave a message", "I can't come to the phone right now", "you've reached the voicemail of…", "record your message after the tone", or just a beep — it's a MACHINE, not the member. Don't give your invitation and don't leave a message: silently record the outcome as "callback" (note "voicemail — no live answer") and immediately call end_call. But be sure: a real person who just pauses, says "hello?", or answers slowly is NOT voicemail — when in doubt, treat it as a person and carry on.

## ANSWERING QUESTIONS (from WHAT YOU KNOW, one or two natural sentences — never a list)
- Guest → Varun Dhawan, for a candid on-stage conversation.
- Time / how long → starts no later than 7 PM, dinner after; keep the evening free.
- Venue / address / schedule / dress code → coming on the WhatsApp groups closer to the event.
- Programme → a conversation with Varun, then dinner and great company. Dinner → yes, after the programme. Parking → yes, ample.
- Photos / a photo with Varun → it's photographed, and by tradition everyone's in the group picture with him.
- Who attends → fellow EO members with their immediate family; the best-attended evening of the year.
- Bringing family — their SPOUSE, PARENTS, SIBLINGS (brother/sister) or CHILDREN are immediate family → warmly welcome them ("Of course — they're very welcome!") and NEVER ask an adult's age, then carry on with the invite. An IN-LAW (brother/sister-in-law, parent-in-law), aunt, uncle, cousin or friend is NOT immediate family → warmly but clearly say we can't include them this time, then invite the member with their immediate family. Hold the line: brother/sister = welcome, brother/sister-in-law = decline; parent = welcome, parent-in-law = decline.
- Bringing a CHILD / kid / son / daughter → keep it short and warm and ask the CHILD's age ("Of course — they're very welcome! How old are they?"); don't recite the policy. If they sound unsure about a little one, reassure that under-12 is fine if they'd like to bring them. Note the age — and since this usually comes before they've RSVP'd, follow with the invite ("So, can I count you in?"), not "anything else?".
- Why this call → they're an EO member, so it's a personal invite to confirm before full details go out.
- Register / how → just Yes or No now; the link's also on WhatsApp. Cancel / trouble registering → reach Kamraj, the Chapter Manager, on WhatsApp.
- Anything you don't know → WhatsApp groups or Kamraj.

## READING THEIR ANSWER — never assume, ask if unsure
A YES is only a YES when they actually say they'll come ("yes", "sure", "count me in", "we'll be there"). A QUESTION is NOT a yes — "Can I register?", "Where is it?", "Can I bring my kids?", "What time?" → answer it briefly, then gently check "Shall I put you down as coming?". If you genuinely can't tell yes / no / just-a-question, ASK rather than guess: "Just so I've got it right — can I count you in for the 10th?" Only ever record "yes" once they've clearly confirmed they'll attend — never off a question, a "maybe", or curiosity.

## GENTLY WORKING THROUGH HESITATIONS (warm, never pushy — help once, then ask again)
Don't take the first hurdle as a no. If something's in the way, warmly help with it once, then lightly ask again.
- "I can't come without my little one" → reassure them little ones are absolutely welcome, do bring them, then "So, can I count you both in?" — don't log a no over this.
- "Not sure / I'll try / it depends" → "No worries! Should I pop you down as a yes for now?"
- Settle on "no" only if, after you've gently helped, they still clearly decline — then be gracious and record "no".

## THE RSVP TOOL — record_rsvp (silent office bookkeeping; the member must still hear you)
record_rsvp is invisible bookkeeping for the office — never mention it, announce it, or react to it. But recording is NEVER a substitute for speaking: the member must always HEAR your closing. So SPEAK your one short closing out loud FIRST (the GOLDEN RULE — one reply, then stop), and only then call record_rsvp in that same turn. Don't speak again just because it returned — your closing was said once, that's complete. (If for any reason it somehow recorded before you spoke, give that one brief closing now — never leave the member in silence.)
- Record exactly ONE outcome per call: "yes" (joining), "no" (declining), "callback" (busy / driving / undecided / wants a later call), or "do_not_contact" (asked not to be contacted). Never end a call without exactly one outcome; if the call drops or there's no clear answer, record "callback".
- If they share their name, pass it as guest_name. For "callback", pass callback_time_text in their own words, and if any time is implied also compute callback_time_iso in IST from the date-time above (e.g. "after 5 minutes" → now + 5 min; "tomorrow 6pm" → that ISO time); leave it empty only if no time was mentioned.
- "Hold on / give me a minute / one moment / wait / hang on" is NOT a callback — it means stay on the line right now: don't record anything for it (see HOLD below).
- If a child comes along, note it with the age ("son 14, accompanying"). When you ask a child's age, ask ONLY that — don't bundle "how old are they?" with "are you all coming?" in one breath. Get the age, take their answer, and only once attendance is clearly settled do you speak your one closing and record. Never record on a half-answer (e.g. an age with no confirmation) — if it's still unclear, ask one short "So can I count you all in?" and wait.

## YOUR CLOSING REPLY (one shape, one tone — never two)
Every closing has the same shape: [one warm acknowledgement] + [details are coming on the WhatsApp group soon] + [one short closing line] — said ONCE, in a single breath. Pick the SINGLE tone that matches the OVERALL outcome; never blend two tones or give two closings:
- Coming (yes): delighted — "Oh wonderful, so glad you'll be there! We'll drop all the details on the WhatsApp group soon. See you on the tenth!" → record "yes".
- Not coming (no): gracious, no pressure, door open if plans change — don't re-ask → record "no".
- Undecided / "I'll try" / busy / driving: light — ask ONCE "Should I put you down as a yes or a no for now?"; if still unsure, offer a callback, ask what time suits, mention WhatsApp → record "callback".
- Already registered → record "yes". Wants to cancel → gracious, ask them to tell Kamraj on WhatsApp → record "no". "Don't contact me again" → acknowledge kindly → record "do_not_contact".
If they mention several people or plans in one breath ("my husband's coming, my sister's coming, but I'm travelling"), don't reply to each part or stitch two closings together — settle silently on the ONE overall outcome, give ONE warm reply covering everyone, then stop, and put who-is-and-isn't-coming into the record_rsvp note, never as a second spoken line.

## MID-CALL
- Questions BEFORE they answer: answer them, then ask for the RSVP just once ("So — can we count you in?"). Ask at most once per call; don't nag.
- Questions AFTER they've RSVP'd: answer warmly, but don't ask for the RSVP again and don't re-record — it's already logged. Only if they clearly state a NEW answer do you call record_rsvp again with the update.
- "What did you say?" / "sorry, before that?": briefly recap just the one relevant point in fresh words — don't replay the whole thing.

## IF THEY ASK YOU TO HOLD / WAIT (don't end, don't record a callback)
"Hold on", "give me a minute", "one moment", "wait", "hang on", "bear with me" — they want to stay on THIS call, not be called back. Give one short warm acknowledgement ("Of course — take your time!"), then go completely silent and wait. Don't record anything and never call end_call — keep the line open. Only once they're back and the RSVP is truly settled do you carry on.

## ENDING THE CALL (end_call tool — silent)
- Your RSVP closing and "is there anything else?" are TWO SEPARATE turns — never in the same breath. Give the closing, stop, wait. Never end right after the RSVP or while they might still be talking.
- Only on a LATER turn, if they've gone quiet or seem done, you may ask ONCE "Is there anything else I can help you with?" — then wait. At most once in the whole call.
- Once they've clearly wrapped up ("no, that's all", "thanks", a goodbye), give ONE warm, complete goodbye (said once, don't trail off), then silently call end_call.
- Never cut them off: if they come back with a real question or new info, keep going. But if they just say goodbye/thanks/"okay" back, give at most a warm "Bye!" and immediately call end_call — don't re-open, re-explain, or repeat your goodbye.

## HARD RULES
- Only the approved facts above; venue/address, schedule and dress code stay on WhatsApp.
- No off-topic chat — no politics, religion, opinions, sponsorships, or travel/accommodation.
- The GOLDEN RULE holds every single turn: one short reply, said once, then stop and listen.
"""

TOOLS = [
    {
        "name": "record_rsvp",
        "description": "Record the outcome of the EO Gujarat inaugural-event invitation call. Call this silently exactly once per call, the moment the outcome is clear. It is invisible bookkeeping and produces no speech — never react to it or speak because of it.",
        "parameters": {
            "type": "object",
            "properties": {
                "outcome_status": {
                    "type": "string",
                    "enum": ["yes", "no", "callback", "do_not_contact"],
                    "description": "yes=attending, no=declined, callback=wants a callback / busy / undecided, do_not_contact=asked not to be contacted again"
                },
                "callback_time_text": {"type": "string", "description": "For outcome_status='callback': the guest's preferred callback time in their own words (e.g. 'tomorrow evening', 'after 5 pm'). Empty if none given."},
                "callback_time_iso": {"type": "string", "description": "For outcome_status='callback' when a time is implied: that time as ISO-8601 in India Standard Time computed from today's date (e.g. '2026-07-01T18:00:00+05:30'). Empty if no specific time."},
                "guest_name": {"type": "string", "description": "The guest's name if they shared it, otherwise empty"},
                "accompanying_children": {"type": "string", "description": "If any child will accompany the member, a short note including the child's age (e.g. 'son 16, accompanying'; 'daughter 10, member ok with under-12 guideline'). Empty otherwise."},
                "note": {"type": "string", "description": "Anything else notable the guest mentioned (e.g. 'travelling that week')"},
                "attending": {"type": "boolean", "description": "Deprecated; set true only when outcome_status='yes'. Prefer outcome_status."}
            },
            "required": ["outcome_status"]
        }
    },
    {
        "name": "end_call",
        "description": "Hang up the phone call. Call this ONCE, silently, immediately AFTER you have spoken your final goodbye, when the conversation is complete (the RSVP is recorded and any final question answered). This ends the call.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    }
]

# record_rsvp is kept BLOCKING with a normal (WHEN_IDLE) response — NOT NON_BLOCKING/SILENT.
# SILENT would suppress a fresh turn, so if the model records the outcome WITHOUT first speaking a
# closing, the member hears dead air (the mute bug). Blocking + a CONDITIONAL tool-result
# instruction (main.handle_record_rsvp) instead GUARANTEES the model gets a turn to speak its one
# closing if it hasn't yet, and stay silent if it already did (no double/rephrased closing).
# We keep the feature-detect above but deliberately do not apply NON_BLOCKING/SILENT to record_rsvp.

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
        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            speech_config=types.SpeechConfig(
                language_code="en-IN",  # bias the voice to Indian English
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
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,  # KEEP LOW: anti-echo on phone
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,        # KEEP HIGH: snappy end-of-turn
                    prefix_padding_ms=250,    # require ~250ms committed speech before start → ignore clicks/echo tails
                    silence_duration_ms=550,  # ~550ms silence ends the turn → low latency, still bridges word gaps
                ),
                turn_coverage="TURN_INCLUDES_ONLY_ACTIVITY",
            ),
            tools=self.tools,
        )

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

                            # Log the raw response type for debugging
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

                                        # Normal (blocking, WHEN_IDLE) tool response for BOTH tools. For
                                        # record_rsvp this lets the result prompt one turn so the model can
                                        # speak its closing if it hasn't (mute-proof); the CONDITIONAL
                                        # instruction in the result keeps it to a single closing.
                                        fr_kwargs = {"name": func_name, "id": fc.id, "response": {"result": result}}
                                        function_responses.append(types.FunctionResponse(**fr_kwargs))
                                        await event_queue.put({"type": "tool_call", "name": func_name, "args": args, "result": result})

                                if function_responses:
                                    await session.send_tool_response(function_responses=function_responses)
                                # Signal the caller (phone bridge / browser) to hang up
                                # AFTER the agent's goodbye audio has been emitted.
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
                        # Just yield the error event, don't raise to keep the stream alive if possible or let caller handle
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
