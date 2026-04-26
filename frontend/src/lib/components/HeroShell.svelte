<script lang="ts">
  import { goto } from "$app/navigation";

  type Accent = "teal" | "violet" | "amber" | "slate" | "emerald" | "blue";

  type Props = {
    size: "tile" | "full";
    accent: Accent;
    label: string;
    range?: string;
    headline?: string;
    sub?: string;
    href?: string;
    children?: import("svelte").Snippet;
  };

  let { size, accent, label, range, headline, sub, href, children }: Props =
    $props();

  const accentBar: Record<Accent, string> = {
    teal: "bg-brand-teal",
    violet: "bg-brand-violet",
    amber: "bg-brand-amber",
    slate: "bg-border-strong",
    emerald: "bg-brand-emerald",
    blue: "bg-brand-blue",
  };
  const accentText: Record<Accent, string> = {
    teal: "text-brand-teal",
    violet: "text-brand-violet",
    amber: "text-brand-amber",
    slate: "text-text-muted",
    emerald: "text-brand-emerald",
    blue: "text-brand-blue",
  };

  function handleClick() {
    if (href) void goto(href);
  }
</script>

<div
  class={`relative overflow-hidden rounded-lg border border-border bg-bg-panel ${size === "tile" ? "p-3" : "p-4"} ${href ? "cursor-pointer transition hover:border-border-strong" : ""}`}
  role={href ? "link" : undefined}
  tabindex={href ? 0 : undefined}
  onclick={handleClick}
  onkeydown={(e) => {
    if (href && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      handleClick();
    }
  }}
>
  <div class={`absolute left-0 top-0 h-full w-[3px] ${accentBar[accent]}`}></div>
  <div class="flex items-baseline justify-between">
    <div class={`text-[10px] font-medium uppercase tracking-wide ${accentText[accent]}`}>
      {label}
    </div>
    {#if range}
      <div class="text-[10px] text-text-subtle">{range}</div>
    {/if}
  </div>
  {#if headline}
    <div class={`mt-1 font-mono ${size === "tile" ? "text-base" : "text-2xl"} font-semibold text-text`}>
      {headline}
    </div>
  {/if}
  <div class={size === "tile" ? "mt-1" : "mt-3"}>
    {@render children?.()}
  </div>
  {#if sub}
    <div class="mt-1 text-[10px] text-text-subtle">{sub}</div>
  {/if}
</div>
