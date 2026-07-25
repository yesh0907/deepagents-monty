# Deep Agents Code Interpreter alignment research

Research date: 2026-07-25. This note is intentionally investigative; it does
not propose an implementation commitment.

## What is current

The official implementation is `langchain-quickjs`, housed in the Deep Agents
monorepo. The latest repository tag is
[`langchain-quickjs==0.3.4`](https://github.com/langchain-ai/deepagents/releases/tag/langchain-quickjs%3D%3D0.3.4),
cut on 2026-07-24. Its package changelog contains only a minimum
`quickjs-rs==0.2.5` fix plus a shared Deep Agents Code model-support change, so
there is no new interpreter API in 0.3.4 itself
([0.3.4 changelog](https://github.com/langchain-ai/deepagents/blob/langchain-quickjs%3D%3D0.3.4/libs/partners/quickjs/CHANGELOG.md#034-2026-07-24)).
Deep Agents itself first advertised the experimental middleware in 0.6.0
([Deep Agents changelog](https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/CHANGELOG.md#060-2026-05-12)).

The meaningful current design, accumulated through 0.3.x, is:

- `CodeInterpreterMiddleware` exposes a capability-scoped, persistent QuickJS
  REPL, with configurable memory, timeout, tool name, console capture, output
  size, per-eval host-call budget, persistence mode, and snapshot size
  ([middleware source](https://github.com/langchain-ai/deepagents/blob/langchain-quickjs%3D%3D0.3.4/libs/partners/quickjs/langchain_quickjs/middleware.py)).
- Persistence is explicit: `thread`, `turn`, or `call`. Thread mode restores a
  graph-state snapshot in `before_agent`, saves it in `after_agent`, then evicts
  the live runtime. The private state field uses `PrivateStateAttr`
  ([middleware lifecycle](https://github.com/langchain-ai/deepagents/blob/langchain-quickjs%3D%3D0.3.4/libs/partners/quickjs/langchain_quickjs/middleware.py#L333-L527)).
- Thread snapshots are delta encoded with `bsdiff4` through a LangGraph
  `DeltaChannel`; the source reports full heaps of roughly 1.4 MB and typical
  patches of roughly 200 B–1 KB
  ([snapshot implementation](https://github.com/langchain-ai/deepagents/blob/langchain-quickjs%3D%3D0.3.4/libs/partners/quickjs/langchain_quickjs/_snapshot.py)).
- Programmatic tool calling (PTC) accepts an explicit allowlist of live tool
  names and/or `BaseTool` objects. It exposes them as typed-looking
  `tools.<camelCase>()` functions, rejects invalid identifiers, deduplicates
  names, prevents recursive exposure of `eval`, and reserves `task` for its
  richer top-level bridge
  ([PTC implementation](https://github.com/langchain-ai/deepagents/blob/langchain-quickjs%3D%3D0.3.4/libs/partners/quickjs/langchain_quickjs/_ptc.py)).
- The PTC set is resolved from `ModelRequest.tools` on every model call, so it
  respects upstream middleware that filters the live tool list. Matching
  schema-derived prompt text is generated and cached
  ([call preparation](https://github.com/langchain-ai/deepagents/blob/langchain-quickjs%3D%3D0.3.4/libs/partners/quickjs/langchain_quickjs/middleware.py#L402-L468)).
- `task()` is a first-class interpreter global rather than an ordinary PTC
  tool. It supports a subagent type, UI label, and response schema. The 0.3.3
  release specifically fixed propagation of subagent interrupts
  ([0.3.3 changelog](https://github.com/langchain-ai/deepagents/blob/langchain-quickjs%3D%3D0.3.4/libs/partners/quickjs/CHANGELOG.md#033-2026-07-16),
  [subagent bridge](https://github.com/langchain-ai/deepagents/blob/langchain-quickjs%3D%3D0.3.4/libs/partners/quickjs/langchain_quickjs/_subagent.py)).
- Results and captured console output are independently bounded and formatted
  into distinct result/stdout blocks. Cancellation is allowed to propagate
  rather than being converted into a model-visible runtime error
  ([official package README](https://github.com/langchain-ai/deepagents/blob/langchain-quickjs%3D%3D0.3.4/libs/partners/quickjs/README.md)).
- The public docs emphasize that this is an in-process capability boundary, not
  host-memory isolation, and that restoring interpreter state does not reverse
  external tool side effects
  ([interpreter guide](https://docs.langchain.com/oss/python/deepagents/interpreters)).

## What Deep Agents Code adds around the middleware

The initial Deep Agents Code integration deliberately treats the interpreter as
an opt-in subsystem rather than merely appending one more tool
([integration commit](https://github.com/langchain-ai/deepagents/commit/f0ca89c9c63f5cb5fe8e218014098756570299d5)):

- configuration covers enablement, timeout, memory, maximum PTC calls, maximum
  result characters, and PTC policy;
- the dependency is imported lazily;
- it renames the generic tool to `js_eval`;
- PTC defaults off, while `"safe"` expands only to read-only
  `read_file`/`glob`/`grep`;
- explicit tool names are validated against the live toolset;
- `"all"` requires an unsafe acknowledgement unless the whole agent already
  auto-approves tools, and write/shell exposure is logged;
- remote-sandbox combination and subagent inheritance were intentionally
  rejected in v1 rather than left ambiguous.

These guardrails exist because both PTC tool calls and interpreter `task()`
dispatches bypass the parent `ToolNode`'s per-call HITL checks. The middleware
documents the same limitation directly
([middleware API warning](https://github.com/langchain-ai/deepagents/blob/langchain-quickjs%3D%3D0.3.4/libs/partners/quickjs/langchain_quickjs/middleware.py#L122-L182)).

## Candidates for `deepagents-monty`

### Strong near-term candidates

1. **Bound returned data.** Add a `max_result_chars`-style limit covering both
   the final value and captured stdout, and bound stdout while collecting it.
   Monty currently accumulates both without a limit. This is small, directly
   protects model context, and matches the Deep Agents API.
2. **Add an external-call budget.** Monty's `external_functions` are analogous
   to PTC but currently have no per-snippet call cap. A
   `max_external_calls` default and model-visible budget error would limit
   accidental or adversarial loops.
3. **Make persistence policy explicit.** Replace the single implicit
   persistence behavior plus `restart` escape hatch with `thread`/`turn`/`call`
   modes (retaining `restart` if useful for compatibility). This clarifies
   lifecycle guarantees and enables stateless deployments.
4. **Cap serialized REPL state.** Add `max_snapshot_bytes` and fail/drop state
   predictably when exceeded. Monty currently writes a full base64 dump after
   every successful or failed tool call. First measure real dump sizes before
   deciding whether a delta channel is worth the extra dependency and
   complexity.
5. **Use private graph state and lifecycle hooks.** Evaluate moving snapshot
   restore/save to `before_agent`/`after_agent`, marking the state private, and
   returning ordinary `ToolMessage`s from execution. This would align with
   current middleware composition and avoid coupling every eval result to a
   `Command` state update. Compatibility with multiple evals in one agent turn
   must be proven first.

### Valuable, but needs an API/design discussion

6. **Offer tool-native programmatic calls.** Build an opt-in allowlist accepting
   tool names and `BaseTool` instances, translate schemas to Monty/Python stubs,
   and install narrow Python globals. Resolve names from `request.tools` each
   call so upstream filtering remains authoritative. This would make
   `external_functions` easier to use without replacing that lower-level API.
7. **Copy Deep Agents Code's safety presets.** Default tool bridging off; offer
   a clearly read-only preset; validate explicit names; require acknowledgement
   for all-tools exposure; and log write/network/shell capabilities. Do not
   imply that prompt text enforces HITL.
8. **First-class subagent bridge.** A top-level `task(...)` with structured
   response schemas could bring Monty feature parity, but interrupt propagation,
   nested middleware, event/UI metadata, and HITL semantics make this a larger
   feature than generic host functions.
9. **Generate prompt/API text from live capabilities.** Monty already derives
   stubs from Python callables. Extend that mechanism so prompt text,
   signatures, sync/async guidance, and the actually installed allowlist share
   one source of truth; cache stable renderings and snapshot-test variants.
10. **Normalize operational metadata and errors.** Attach
    `ls_code_input_language="python"` tool metadata, define stable error
    categories (timeout, resource exhaustion, call budget, concurrent eval),
    and ensure cancellation propagates cleanly.

## Suggested discussion order

Start with output/state limits because they are low-risk hardening. Then decide
whether parity means only a consistent configuration surface or also
tool-native programmatic calling. That decision determines whether persistence
lifecycle, HITL bypass policy, and a subagent bridge should be designed
together or remain independent.
