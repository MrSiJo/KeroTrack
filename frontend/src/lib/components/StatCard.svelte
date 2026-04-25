<script lang="ts">
  type Props = {
    label: string;
    value: string;
    unit?: string;
    sub?: string;
    tone?: "default" | "amber" | "red" | "emerald";
  };
  let { label, value, unit = "", sub = "", tone = "default" }: Props = $props();

  const toneClass: Record<string, string> = {
    default: "text-text",
    amber: "text-brand-amber",
    red: "text-brand-red",
    emerald: "text-brand-emerald",
  };
</script>

<div class="rounded-lg border border-border bg-bg-panel px-4 py-3">
  <div class="text-xs uppercase tracking-wide text-text-label">{label}</div>
  <div class="mt-1 flex items-baseline gap-1">
    <span class={`font-mono text-2xl font-semibold ${toneClass[tone]}`}>{value}</span>
    {#if unit}<span class="text-sm text-text-muted">{unit}</span>{/if}
  </div>
  {#if sub}<div class="mt-1 text-xs text-text-subtle">{sub}</div>{/if}
</div>
