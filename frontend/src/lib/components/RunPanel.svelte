<script lang="ts">
  import { api, ApiError } from "$lib/api";
  import { liveStatus } from "$lib/stores/liveStatus";

  type JobName = "analysis" | "cost_analysis" | "notifier";
  type RunState = {
    busy: boolean;
    ok: string | null;
    error: string | null;
  };

  let states = $state<Record<JobName, RunState>>({
    analysis: { busy: false, ok: null, error: null },
    cost_analysis: { busy: false, ok: null, error: null },
    notifier: { busy: false, ok: null, error: null },
  });

  function clearLater(name: JobName) {
    setTimeout(() => {
      states = { ...states, [name]: { busy: false, ok: null, error: null } };
    }, 4000);
  }

  async function runJob(name: JobName, opts: { test?: boolean } = {}) {
    states = { ...states, [name]: { busy: true, ok: null, error: null } };
    try {
      const result = await api.runJob(name, opts);
      let summary = "ok";
      if (name === "notifier") {
        const sent = (result as { sent?: boolean }).sent;
        const reason = (result as { skipped_reason?: string | null })
          .skipped_reason;
        summary = sent ? "sent" : reason ?? "skipped";
      } else if (name === "analysis") {
        summary = "analysed";
      } else if (name === "cost_analysis") {
        summary = "costs updated";
      }
      states = {
        ...states,
        [name]: { busy: false, ok: summary, error: null },
      };
      // Pull fresh status now (SSE will also fire from the publisher).
      void liveStatus.refresh();
    } catch (err) {
      const msg =
        err instanceof ApiError ? err.message : (err as Error).message;
      states = {
        ...states,
        [name]: { busy: false, ok: null, error: msg },
      };
    } finally {
      clearLater(name);
    }
  }
</script>

<section class="rounded-lg border border-border bg-bg-panel p-4">
  <div class="flex items-baseline justify-between">
    <h2 class="text-xs font-semibold uppercase tracking-wide text-text-label">
      Run now
    </h2>
    <span class="text-[10px] text-text-subtle">
      results stream in via SSE
    </span>
  </div>
  <div class="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
    <button
      class="flex flex-col rounded border border-border bg-bg-elev px-3 py-2 text-left text-sm transition hover:border-brand-blue disabled:opacity-50"
      on:click={() => runJob("analysis")}
      disabled={states.analysis.busy}
    >
      <span class="font-medium text-text">
        {states.analysis.busy ? "Running…" : "Analysis"}
      </span>
      <span class="mt-0.5 text-[11px] text-text-subtle">
        forecast + days remaining
      </span>
      {#if states.analysis.ok}
        <span class="mt-1 text-[11px] text-brand-emerald">{states.analysis.ok}</span>
      {:else if states.analysis.error}
        <span class="mt-1 text-[11px] text-brand-red">{states.analysis.error}</span>
      {/if}
    </button>

    <button
      class="flex flex-col rounded border border-border bg-bg-elev px-3 py-2 text-left text-sm transition hover:border-brand-blue disabled:opacity-50"
      on:click={() => runJob("cost_analysis")}
      disabled={states.cost_analysis.busy}
    >
      <span class="font-medium text-text">
        {states.cost_analysis.busy ? "Running…" : "Costs"}
      </span>
      <span class="mt-0.5 text-[11px] text-text-subtle">
        per-period cost summary
      </span>
      {#if states.cost_analysis.ok}
        <span class="mt-1 text-[11px] text-brand-emerald">
          {states.cost_analysis.ok}
        </span>
      {:else if states.cost_analysis.error}
        <span class="mt-1 text-[11px] text-brand-red">
          {states.cost_analysis.error}
        </span>
      {/if}
    </button>

    <button
      class="flex flex-col rounded border border-border bg-bg-elev px-3 py-2 text-left text-sm transition hover:border-brand-blue disabled:opacity-50"
      on:click={() => runJob("notifier", { test: true })}
      disabled={states.notifier.busy}
    >
      <span class="font-medium text-text">
        {states.notifier.busy ? "Sending…" : "Test Gotify"}
      </span>
      <span class="mt-0.5 text-[11px] text-text-subtle">
        one-shot, bypasses schedule
      </span>
      {#if states.notifier.ok}
        <span class="mt-1 text-[11px] text-brand-emerald">{states.notifier.ok}</span>
      {:else if states.notifier.error}
        <span class="mt-1 text-[11px] text-brand-red">{states.notifier.error}</span>
      {/if}
    </button>
  </div>
</section>
