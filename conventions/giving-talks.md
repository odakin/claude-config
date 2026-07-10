<!-- doc-meta
when: 講演・セミナー・発表の準備をするとき
category: paper
summary: 講演のしかた (= Robert Geroch "Suggestions For Giving Talks" arXiv:gr-qc/9703019 の own-words ダイジェスト、 主題選択 / 3-4 メッセージ構成 / 導入は全体の 1-5 / 視覚資料は図>言葉>式 / 1h で非自明な式 5 本・スライド 10 枚 / 質問は完全に正直に 等。 セミナー・JC・卒論発表の準備時に読む、 英語本体)
-->
# Giving talks — Robert Geroch's suggestions, distilled

A practical checklist for preparing and delivering a research talk (seminar, colloquium,
conference talk, journal club, thesis defense). **Load this when** preparing slides or a
talk outline, rehearsing, or advising someone on a presentation. (For the *technical* side of
building slides — Beamer/metropolis, figure generation, reproducible PDF build, page-label
fixes — see [beamer-slides.md](beamer-slides.md).)

This is an **own-words distillation** of **Robert Geroch, "Suggestions For Giving Talks,"
arXiv:gr-qc/9703019** (an essay of roughly 4500 words; written ~1973, posted to arXiv in
1997). It tries to capture every point he makes, reorganized as a working checklist — but
it is a summary, not the original text. For his exact wording and full reasoning, read the
source: https://arxiv.org/abs/gr-qc/9703019

## Core principle

A talk has one job: **to get a specific set of ideas to take hold in the listeners' minds.**
What matters is not how much information you emit but how much the audience absorbs. Talking
about physics is a different activity from thinking about physics, with a different goal — so
a talk must be organized differently from your private understanding. Aim every decision at
what the audience will actually walk away with.

Corollary on getting better: simply giving more talks does little after the first few. What
helps is deliberate reflection at two moments — right after you give a talk, and while you
sit through other people's talks.

## 1. Choosing the subject

- **Go broad.** Pick the most general version of the topic you can handle comfortably —
  deliberately broader than your own narrow research problem. The audience lacks all the
  context that makes your narrow problem feel important; the broad framing gives them a place
  to stand. (E.g. talk about "conservation laws in general relativity" — spinning and charged
  particles, particle decay, the link to stress-energy — rather than narrowly about your own
  result on "Killing tensors.")
- **Calibrate to the audience's unfamiliarity.** The fraction of your material that is new to
  the listeners depends on who they are — very roughly 90% new for non-specialists, ~60% for
  colleagues in the broad field, ~35% for specialists in your subfield. Set the level of
  generality to match.
- **The title is the single most important choice for attendance** — it is how people decide
  whether to come. A good title states the subject, signals the level, is engaging without
  being cute, and uses words the audience already knows. Questions and flat assertions both
  make good titles. (E.g. prefer "Black Holes are Stable" over the dull "Perturbations of the
  Kerr Solution" or the opaque "Linearized Fields in a Kerr Background Metric.")

## 2. The plan: three or four messages

- **Organize the whole talk around three or four "messages"** (three is slightly better). A
  message is one important point with its supporting arguments and examples, or a cluster of
  closely related remarks. Each becomes, in effect, its own small talk inside the talk.
- **Give each message a title** (e.g. "The initial-value formulation of general relativity")
  and **a one-sentence, non-technical summary** that captures its essence.
- **Three-or-four is a hard cognitive limit.** Audiences cannot retain more than that many
  essential points — do not exceed it.
- **Expect to recast your material.** Your private thinking is a web of many small,
  interconnected points; a talk is three or four big ones. Getting to that form usually means
  dropping detail and connections, and sometimes adding new material so each message stands
  complete on its own.
- The hard balance: each message must be specific and cohesive enough to be memorable as a
  unit, yet general enough that together they tell your whole story. Draft several
  organizations and pick the strongest to refine.

## 3. The introduction (about one-fifth of the talk)

Two jobs:

**(a) Place the subject in context.** Start at the broadest sensible level and descend to your
specific topic in three or four steps. For a general audience, open with broad recent trends
in physics; for specialists, with current directions or open problems in the wider field.
**Repeat the context even if the audience probably knows it** — it establishes the frame
everyone needs. (If there is no single natural context for the subject, make one up.) Stress
what kind of problem you address and why: Why study this? Why is it
interesting? What has it taught us about nature? Where do things stand, and where are they
heading? An optimistic framing of the future builds enthusiasm.

**(b) Announce the structure.** Tell them the three or four messages up front — each title plus
a few descriptive sentences. Put the titles where everyone can see them, and check them off as
you deliver them. Explain how the messages relate and how together they sum up the subject,
and state the general conclusions in advance if you can. In effect: give a short talk about
the structure of your talk.

## 4. The body

- **Mark every message boundary explicitly.** Open each message by restating its title, saying
  you are starting it, and previewing its content ("We now begin our discussion of..."). Close
  it by saying it is finished and giving a three-or-four-sentence non-technical summary ("To
  summarize,..."). These closing summaries matter especially: they let the audience consolidate
  what you said, and let anyone who got lost rejoin the thread. Make transitions between
  messages unmistakable.
- **Keep re-orienting the audience.** Periodically restate the overall plan, where you are in
  it, and how the messages connect. The audience should always know where they are.
- **Treat each message as a self-contained mini-talk** with one clear objective, typically
  three to six specific points; re-summarize any earlier material you rely on.
- **Suppress everything that does not advance the current message.** Concretely:
  - **Notation:** adjust it to introduce as few symbols and variables as possible.
  - **Definitions:** rephrase them to avoid dragging in extra concepts.
  - **Framing:** present things from whatever angle keeps side issues from arising — even a
    "less correct" viewpoint, if it serves the point.
  - **Analogies:** use them to skip detailed treatment and let listeners resolve their own
    questions; especially useful for topics with many parts.
  - **Calculations:** show only the inputs and the outputs; collapse a chain of consecutive
    calculations into one and give the overall input and output.
- It is sometimes right to say something technically incomplete, or even slightly wrong, to
  keep a message clear. Clarity and forward motion beat completeness. Cut tangents entirely.

## 5. The conclusion

- Summarize the main points in non-technical language, restate the context, and pull the
  messages together into a single whole.
- State the questions still worth pursuing; optionally, predict where the subject is heading.

## 6. Visual material

- **Hierarchy: figures beat words; words beat equations.**
- **Figures.** Express ideas as figures, graphs, or tables whenever you can — far more concepts
  reduce to a picture than you would expect. Keep them simple and drop inessential detail;
  label everything labelable; title every figure on a slide. Make sure every mark is
  understandable to the audience and remove anything they cannot read. Leave time to absorb a
  figure and talk through it while it is up, even when it is well labeled. One strong figure
  beats several weak ones.
- **Words on slides.** When a point or argument is verbal, put a short summary on the slide or
  board for emphasis. A full sentence is fine (one or two per slide at most); for a multi-step
  argument, list the steps as short phrases to expose the structure. (To put a theorem on a
  slide, condense its complicated conditions into a short descriptive phrase in quotation
  marks.) It is fine to read displayed text aloud. Keep each slide up for several minutes; if something would only be
  shown briefly, fold it into another slide as a phrase instead.
- **Equations.** Treat an equation as a tool for making a point, not as data for the audience
  to copy down. Present it as a "picture" to be described, discussed, and interpreted
  physically. Define and discuss every symbol — and repeat the meanings even in later
  equations. Spend a few minutes on each important equation. Use **at most about five
  non-trivial equations in an hour-long talk.** Simplify with a clever choice of variables
  (let one symbol stand for a whole complicated thing), batch terms into phrases ("+ small
  terms"), and replace terms you will not discuss with a few words about why they do not
  matter — and where possible eliminate an equation entirely via a symbol or a sentence.
- **Slide count.** Aim for **about ten slides per hour**, each on screen and under discussion
  roughly 70% of the time.

## 7. Delivery and general suggestions

- **Voice.** Speak loudly, firmly, with conviction. Build sentences you can stand behind;
  avoid hedging ("sort of true," trailing off). Cast even a rough physical argument as a
  deliberate, defensible statement ("In physical terms,..."). Use complete sentences while you
  think on your feet.
- **Be explicit; kill pronouns.** Say "that tensor," not "that"; "the five-gram mass," not
  "m₁." Avoid bare "this"/"that" used as nouns, and "it" for named things. Add artificial
  explicitness wherever it helps.
- **Navigate out loud.** Continuously tell the audience what you are doing, how it connects,
  where you are headed, and where you are now. Flag an example as an example, and announce when
  you return to the main line.
- **Emphasize deliberately.** Some remarks matter far more than others; signal importance by
  (1) a short, loud, single sentence, (2) repetition, (3) a pause afterward, and (4) saying
  outright "The following point is important." Combine these so that emphasis is distributed
  sensibly rather than spread evenly.
- **Manage energy and time.** Watch faces for comprehension and for boredom; if you are losing
  them, rebuild interest by restating the plan, your location in it, and why the problem
  matters. **Running over time is almost always a disaster** — people get bored and lose the
  earlier thread. Prepare optional, non-essential points (examples) you can include or drop on
  the fly to land on time; if you do run out, stop and give a few-sentence summary.
- **Notes.** Geroch's own system is a single sheet with the outline on one side — the major
  divisions (introduction, message titles, conclusion), each with about five phrase-summarized
  points — and, occasionally, one or two equations on the back. This keeps you flexible and
  not chained to a script.
- **Handle errors live.** If you realize you are seriously wrong or confused, say so and work
  it out with the audience. If you said something unclearly, announce that and rephrase.
- **Questions — be completely honest.** This is the most important rule for Q&A. If an argument
  does not convince the questioner and does not fully convince you, admit it. If asked about
  something you skipped, explain why you simplified and fill it in. If you do not know, say so
  and offer what you can. For a question mid-talk, after answering, climb back to where you
  were by starting general and getting more specific. If mid-talk discussion threatens to take
  over, firmly defer it to the end.

## Improving: watch others, and review yourself

The fastest way to get better is critical reflection at two moments: **immediately after you
speak** (analyze your own organization, clarity, engagement, pacing, and whether the audience
followed), and **while listening to others** (diagnose what works, what doesn't, and why).
