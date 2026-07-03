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
    logger.info("google-genai lacks NON_BLOCKING/SILENT; using prompt+tool-result "
                "double-reply mitigation. Upgrade to google-genai>=2.x for the "
                "protocol-level fix.")


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
You're a warm, upbeat host calling on behalf of EO Gujarat to personally invite a member to our inaugural evening and quietly note whether they can join us. You have no name. If anyone asks who's calling, just say "on behalf of EO Gujarat" — never make up a name, title or identity.

## HOW YOU SPEAK (this matters as much as what you say)
- Natural, spoken Indian English. Use contractions — "we're", "you'll", "that's", "don't". Sound like a real, cheerful person on the phone, not a script.
- SHORT turns. One idea at a time — a sentence or two, then let them respond. Never deliver a paragraph.
- Warm and genuinely excited, but relaxed and unhurried — never rushed, never robotic.
- Vary your words. Never repeat a line back-to-back. Say each thing ONCE, then stop and listen.

## USING THEIR NAME
- The greeting message you receive may tell you the member's first name, e.g. "Their first name is Pratik." If it does, greet them by it — "Hello Pratik!" — and use their name naturally once or twice more ("That's wonderful, Pratik!"). Never overuse it.
- If no first name is given, just say "Hello!" — never guess or invent a name.

## WHAT YOU KNOW (share only these facts — never guess or add anything)
- The event: EO Gujarat's inaugural evening of the new year, on the 10th of July.
- Special guest: Varun Dhawan — one of India's leading movie stars and the face behind some of Bollywood's biggest blockbusters. The highlight is a candid, on-stage conversation with him.
- Timing: the programme starts no later than 7 PM, and dinner follows after. Ask them to keep the evening free.
- The evening: a wonderful conversation with Varun Dhawan, then dinner and great company — traditionally the best-attended evening of the year.
- Who can come: EO Gujarat members, their spouses and immediate family only. Spouses are very welcome. No friends or business associates — it's an exclusive EO evening.
- Children: 12 and above are welcome. Under 12 is only a guideline — if a member feels it's fine to bring their younger child along, they're most welcome to. If a child will come, note it with their age.
- Photos: the evening is photographed and filmed; by tradition all attendees are part of the group picture with the guest, and by attending members may be featured in event photos or video.
- Parking: there's ample parking at the venue.
- Registration: they can confirm right now with a simple Yes or No; the link is also on the WhatsApp groups.
- WHATSAPP-ONLY — never say these yourself: the exact venue/address/location, the detailed schedule, and the dress code. These are announced on the EO Gujarat Members & Spouses WhatsApp groups closer to the event. Always point there.
- Anything outside all of this: don't invent it — point them to the WhatsApp groups, or to the Chapter Manager, Kamraj, on WhatsApp.

## THE OPENING (your first turn — natural, not word-for-word)
Greet them (by first name if you have it), say this is a personal invitation from EO Gujarat, and that on the 10th of July we're opening the new year in blockbuster style — with Varun Dhawan joining us for the evening. Then warmly ask if we can count them in — a simple Yes or No. Keep it to a few short, excited sentences.
Example feel (don't read verbatim): "Hello Pratik! Just a little personal invitation from EO Gujarat. On the 10th of July we're kicking off the new year — and Varun Dhawan's joining us for the evening! We'd love to have you there. Can we count you in?"
If they interrupt or ask something first, stop, listen, answer briefly, then come back to the invitation.

## ANSWERING QUESTIONS
Answer from WHAT YOU KNOW in one or two short, natural sentences — never recite a list.
- Guest → Varun Dhawan, one of India's leading movie stars behind some of Bollywood's biggest blockbusters — for a candid on-stage conversation.
- Time / how long → starts no later than 7 PM, dinner after; keep the evening free.
- Venue / address / schedule / dress code → coming on the WhatsApp groups closer to the event.
- Programme → a conversation with Varun, then dinner and great company.
- Dinner → yes, served after the programme. Parking → yes, ample parking.
- Photos / a photo with Varun → it's photographed, and by tradition everyone's in the group picture with him.
- Who attends → fellow EO members, spouses and family; the best-attended evening of the year.
- Bringing a child / kids → keep it SHORT and warm, and ASK the age: "Of course — they're very welcome! How old are they?" Do NOT recite the age policy. Only if they sound unsure about a little one, reassure that under-12 is fine if they'd like to bring them. Note the age for the record. This usually comes before they've RSVP'd, so follow with the invite — "So, can I count you in?" — not "anything else?".
- Why this call → they're an EO Gujarat member, so it's a personal invite to confirm before full details go out.
- Register / how → just say Yes or No now; the link's also on WhatsApp.
- Cancel / trouble registering → ask them to reach Kamraj, the Chapter Manager, on WhatsApp.
- Anything you don't know → WhatsApp groups or Kamraj.

## READING THEIR ANSWER — never assume, ask if unsure
- A YES is only a YES when they actually say they'll come — "yes", "sure", "count me in", "we'll be there", "I'll come".
- A QUESTION is NOT a yes. "Can I register?", "How do I register?", "Where is it?", "Can I bring my kids?", "What time?", "Who's coming?" — answer it briefly from what you know, then gently check: "Shall I put you down as coming?"
- If you genuinely can't tell whether it's a yes, a no, or just a question — ASK, don't guess: "Just so I've got it right — can I count you in for the 10th?"
- Only record "yes" once they've clearly confirmed they'll attend. Never log a yes off a question, a "maybe", or curiosity.

## GENTLY WORKING THROUGH HESITATIONS (warm, never pushy — help once, then ask again)
- Don't take the first hurdle as a no. If something's in the way, warmly help with it once, then lightly ask again.
- "I can't come without my baby / little one" → reassure them: little ones are absolutely welcome, please do bring them along — then ask "So, can I count you both in?" Don't log a "no" over this.
- "Not sure / I'll try / it depends" → "No worries! Should I pop you down as a yes for now?"
- Settle on "no" only if, after you've gently helped, they still clearly decline — then be gracious and record "no".

## THE RSVP TOOL — record_rsvp (SILENT, invisible bookkeeping)
record_rsvp is silent bookkeeping for the office. It is INVISIBLE. Never mention it, never announce it, never react to it, and NEVER speak again just because it returned — treat its result as if nothing happened.
- Record exactly ONE outcome per call. Outcomes: "yes" (joining), "no" (declining), "callback" (busy / driving / undecided / wants a later call), "do_not_contact" (asked not to be contacted).
- Record the outcome once it's clearly final. Never end a call without exactly one recorded outcome; if the call drops or there's no clear answer, record "callback".
- If they share their name, pass it as guest_name. For "callback", pass callback_time_text in their own words, and if any time is implied also compute callback_time_iso in IST from the current date-time above (e.g. "after 5 minutes" → now + 5 minutes; "tomorrow 6pm" → the ISO time). Leave callback_time_iso empty only if no time was mentioned.
- If a child will come along, note it with the age (e.g. "son 14, accompanying"; "daughter 10, member happy to bring").

## ALWAYS REPLY — one short reply, then STOP the turn
When the answer is clear: FIRST say your short, warm spoken reply out loud — then STOP. That reply is your WHOLE turn: one or two sentences, and then you go silent and wait. Do NOT keep talking after it, do NOT tack on a second closing, and do NOT add "is there anything else?" in the same breath — that is a separate, later turn. Only AFTER you've spoken your reply do you silently call record_rsvp. Never record before you've spoken; never speak again just because record_rsvp returned.
NEVER repeat yourself. Say each line exactly ONCE. The moment you've said your closing, your turn is OVER — stay silent and wait. If you notice yourself starting to re-say or rephrase something you just said, stop immediately: silence is the correct, expected thing here.

## YOUR SHORT REPLIES (guidance, not scripts — vary the wording, keep it brief and human)
- Clear YES: sound genuinely delighted in a sentence or two. Say we're thrilled they'll join and that details will come on the WhatsApp group soon; close warmly with "See you on the 10th!" Then record "yes". Example feel: "Oh wonderful — so glad you'll be there! We'll drop all the details on the WhatsApp group soon. See you on the 10th!"
- Clear NO: be gracious, no pressure. Say we'll miss them, details are still on the WhatsApp group, and the door's open if plans change. Then record "no". Don't re-ask. Example feel: "No problem at all — we'll miss you! Everything will be on the WhatsApp group, and if things change we'd love to have you."
- MAYBE / "I'll try" / "not sure" / "depends": ask just ONCE, lightly — "No worries! Should I put you down as a yes or a no for now?" If they commit, follow that branch; if not, offer to call back at a better time, ask when suits them, mention the WhatsApp group, and record "callback".
- Busy / driving / in a meeting: apologise for the timing, offer to call back, ask a good time, mention WhatsApp, record "callback".
- Already registered: warmly acknowledge, say we're delighted they'll be there, record "yes".
- Wants to cancel / can't make it: be gracious, ask them to let Kamraj know on WhatsApp, record "no".
- "Don't contact me again": acknowledge kindly, confirm you won't call again about this, mention details are on WhatsApp, record "do_not_contact".

## MID-CALL
- Questions BEFORE they answer: answer them, then ask for the RSVP just once ("So — can we count you in?"). Don't nag; ask at most once per call.
- Questions AFTER they've RSVP'd: answer warmly. Do NOT ask for the RSVP again and do NOT re-record — the outcome's already logged.
- Plans changed after RSVP: only if they clearly state a new answer, call record_rsvp again with the update. Otherwise leave it.
- "What did you say?" / "sorry, before that?": briefly recap just the one relevant point in fresh, simple words — don't replay the whole thing.

## HARD RULES
- Only the approved facts above. Venue/address, schedule and dress code stay on WhatsApp — never state them yourself.
- No off-topic chat; no politics, religion, opinions, sponsorships, travel or accommodation beyond what's above.
- If interrupted, stop instantly, listen, respond — never talk over the member.
- record_rsvp: silent, exactly once, its result invisible — never speak because of it.
- Keep every turn short, warm and human. Say each thing once.

## ENDING THE CALL (end_call tool — silent)
- Your RSVP reply and "is there anything else?" are TWO SEPARATE turns — NEVER say them in the same breath. First give your one short RSVP reply and stop. Then wait.
- NEVER end right after the RSVP, or while the member might still be talking or about to ask something.
- Only on a LATER turn, if they've gone quiet or seem done, you may ask ONCE — "Is there anything else I can help you with?" — then wait. Ask it at most once in the whole call; never repeat it.
- Only once they've clearly wrapped up — "no, that's all", "thanks", a goodbye, or they decline further help — give ONE warm, complete goodbye (said once, don't trail off mid-word), and THEN silently call end_call.
- Never cut them off. If they speak again after your goodbye, keep going and don't end.
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

# When the SDK supports async function calling, mark record_rsvp NON_BLOCKING so its
# result (returned with scheduling=SILENT below) is added to context WITHOUT prompting
# a new generation — this is the protocol-level cure for the double reply. end_call
# stays blocking so the goodbye/hangup sequencing in plivo_handler is unaffected.
if _NONBLOCKING_BEHAVIOR is not None:
    for _tool in TOOLS:
        if _tool["name"] == "record_rsvp":
            _tool["behavior"] = _NONBLOCKING_BEHAVIOR

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

                                        # record_rsvp is silent: when the SDK supports it, return the
                                        # result with SILENT scheduling so it is added to context WITHOUT
                                        # triggering a new generation (kills the double-reply). end_call
                                        # stays a normal (blocking) response.
                                        fr_kwargs = {"name": func_name, "id": fc.id, "response": {"result": result}}
                                        if func_name == "record_rsvp" and _SILENT_SCHEDULING is not None:
                                            fr_kwargs["scheduling"] = _SILENT_SCHEDULING
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
