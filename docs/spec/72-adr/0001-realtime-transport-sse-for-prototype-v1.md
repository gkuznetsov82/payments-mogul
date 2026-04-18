# ADR 0001: Realtime Transport for Prototype v1

- **Status:** Proposed
- **Context:**  
  `52-realtime-ui-protocol.md` defines required realtime events (`command_ack`, `action_outcome`, `tick_committed`, `state_snapshot`) but does not lock transport (`WebSocket vs SSE`).  
  For `prototype_vendor_pop_v1`, command submission is already modeled via HTTP control/action endpoints in `51-api-contract.md`, while realtime delivery is primarily server-to-client updates.
- **Decision:**  
  Use **Server-Sent Events (SSE)** as the realtime transport for prototype v1 text client and minimal client UI flows. Keep command submission on HTTP endpoints.
- **Consequences:**  
  - **Positive:** Lower implementation complexity for phase-1 vertical slice; transport aligns with one-way event stream needs.  
  - **Positive:** Easier debugging/observability during early integration because stream remains standard HTTP semantics.  
  - **Positive:** Clean architectural split: HTTP for commands/control, SSE for outbound state/event updates.  
  - **Negative:** No client-to-server messaging over the realtime channel; dual-channel model remains (HTTP + SSE).  
  - **Negative:** If future UX requires high-frequency bidirectional signaling, migration to WebSocket may be warranted.
  - **Follow-up:** Update `52-realtime-ui-protocol.md` to mark SSE as prototype transport and note WebSocket as future option.
  - **Follow-up:** Keep event payload contracts transport-agnostic so migration cost stays bounded.

## Revisit triggers

Re-open this decision if one or more of the following become true:

1. Client commands need to be delivered primarily over the realtime channel (not HTTP).
2. Product scope adds high-frequency bidirectional interactions that are awkward with HTTP + SSE split.
3. Operational constraints show SSE connection behavior is insufficient under target concurrency.
4. Non-browser or multi-client interoperability requirements strongly prefer WebSocket standardization.

## Scope notes

- This ADR applies to **prototype v1** only.
- It does **not** constrain long-term production transport choices.
