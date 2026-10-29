# Where the models sit

Which steps of a brief use a model, what runs where in the two-GPU demo, and which steps can move to a cloud model through an API key. Model choices come from the S8 bench (Bench tab); memory figures are nvidia-smi readings from S8.

## A brief, step by step

![A brief runs top to bottom. Steps 1, 2 and 7 are plain code. Steps 3, 4 and 8 run on local models that stay local. Steps 5 and 6, and the on-request steps below the line, run on local models now and can move to Sonnet. A failed check sends the explanation back once; a second failure shows the lead without an explanation, flagged.](architecture/pipeline.svg)

- **Code, no model:** fetching, eligibility, dates and the citation check are plain code. Numbers and dates are copied from records, never written by a model.
- **Search:** the embedder and reranker are small local models. Nothing in the back-test beat them measurably.
- **Writing:** the profile summary, fit explanation and hand-off draft are written by the chat model. Every one passes both validator layers before it is shown.
- **Grounding check:** Clef reads each sentence beside the record it cites, and flags a sentence the record does not support.
- **Scout and decide:** Scout calls only allowlisted tools. Decide gives typed yes-or-no and score answers with a confidence.

## The demo on two GPUs, and the API swap

![The two-GPU demo layout. GPU A holds the writing and agent models; each of their roles can move to the Anthropic API with one line in .env. GPU B holds the grounding check and search, which have no cloud path. Private mode refuses the path to the API.](architecture/deployment.svg)

- **The swap:** set `PERCH_LLM_<ROLE>=anthropic:claude-sonnet-5-5` for one role, or `PERCH_LLM_DEFAULT` for all of them. Roles are profile summary, fit explainer, hand-off, Scout and decide.
- **What Sonnet measured:** a typical brief took 26 s and cost about $0.09. It passed both checks on 24 of 30 leads, against 28 for Gemma.
- **Decide on Sonnet:** it works, but the Anthropic API returns no token probabilities, so the answer comes without a confidence score.
- **What stays local:** Anthropic offers no embedding or rerank API, and Perch has no adapter for another provider of them. Clef's job needs token scores.
- **The GPU saving:** if every chat role moves to the API, GPU A no longer needs Gemma. Only Clef-flash would stay there, at about 7.4 GB.
- **The layout is planned:** S9 deploys it and measures the two cards together. The memory figures here were measured in separate S8 runs.
- **Private mode:** it is designed and is built in S13. It refuses any model that is not on this server.
