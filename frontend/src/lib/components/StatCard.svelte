<script lang="ts">
  type Props = {
    label: string;
    value: string;
    unit?: string;
    sub?: string;
    tone?: "default" | "amber" | "red" | "emerald";
    compact?: boolean;
  };
  let {
    label,
    value,
    unit = "",
    sub = "",
    tone = "default",
    compact = false,
  }: Props = $props();

  const toneClass: Record<string, string> = {
    default: "text-text",
    amber: "text-brand-amber",
    red: "text-brand-red",
    emerald: "text-brand-emerald",
  };
</script>

<div
  class={`rounded-lg border border-border bg-bg-panel ${compact ? "px-3 py-2" : "px-4 py-3"}`}
>
  <div class="text-[10px] uppercase tracking-wide text-text-label">{label}</div>
  <div class="mt-0.5 flex items-baseline gap-1">
    <span class={`font-mono ${compact ? "text-xl" : "text-2xl"} font-semibold ${toneClass[tone]}`}>
      {value}
    </span>
    {#if unit}<span class="text-xs text-text-muted">{unit}</span>{/if}
  </div>
  {#if sub}<div class="mt-0.5 text-[11px] text-text-subtle">{sub}</div>{/if}
</div>
