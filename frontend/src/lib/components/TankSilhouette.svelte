<script lang="ts">
  type Props = {
    percentage: number;
    litres?: number | null;
    capacity?: number | null;
    bars?: number | null;
    lengthCm?: number;
    heightCm?: number;
  };
  let {
    percentage,
    litres = null,
    capacity = null,
    bars = null,
    lengthCm = 178.5,
    heightCm = 137,
  }: Props = $props();

  // Tank shape — proportions match real-world dimensions.
  const w = 280;
  const h = Math.round((heightCm / lengthCm) * w);
  const pad = 8;
  const innerW = w - pad * 2;
  const innerH = h - pad * 2;

  let pct = $derived(Math.max(0, Math.min(100, percentage)));
  let fillH = $derived((innerH * pct) / 100);
  let fillY = $derived(pad + (innerH - fillH));

  // Tone the fill amber/red as the level drops, per ADR-0004 semantic colour rule.
  let tone = $derived(
    pct <= 15 ? "red" : pct <= 25 ? "amber" : "blue",
  );
  const fillStops: Record<string, [string, string]> = {
    blue: ["#3b82f6", "#1e3a8a"],
    amber: ["#f59e0b", "#92400e"],
    red: ["#ef4444", "#7f1d1d"],
  };

  // 10-bar gauge per mockup. Use sensor's bars_remaining if supplied, else
  // derive from percentage with the same thresholds the backend uses.
  const BAR_THRESHOLDS = [5, 15, 25, 35, 45, 55, 65, 75, 85, 95];
  let computedBars = $derived(
    bars ??
      (() => {
        for (let i = 0; i < BAR_THRESHOLDS.length; i++) {
          if (pct <= BAR_THRESHOLDS[i]) return Math.max(1, i);
        }
        return 10;
      })(),
  );
</script>

<div class="flex items-stretch gap-4">
  <svg
    viewBox={`0 0 ${w} ${h}`}
    class="block flex-1"
    role="img"
    aria-label={`Tank ${pct.toFixed(0)}% full`}
    preserveAspectRatio="xMidYMid meet"
  >
    <defs>
      <linearGradient id="tank-fill" x1="0" x2="0" y1="0" y2="1">
        <stop offset="0%" stop-color={fillStops[tone][0]} stop-opacity="0.85" />
        <stop offset="100%" stop-color={fillStops[tone][1]} stop-opacity="0.95" />
      </linearGradient>
      <clipPath id="tank-clip">
        <rect
          x={pad}
          y={pad}
          width={innerW}
          height={innerH}
          rx="10"
          ry="10"
        />
      </clipPath>
    </defs>

    <!-- shell -->
    <rect
      x="2"
      y="2"
      width={w - 4}
      height={h - 4}
      rx="14"
      ry="14"
      style="fill: rgb(var(--bg-page)); stroke: rgb(var(--border-strong));"
      stroke-width="2"
    />

    <!-- fill (clipped to inner rounded rect) -->
    <g clip-path="url(#tank-clip)">
      <rect
        x={pad}
        y={fillY}
        width={innerW}
        height={fillH}
        fill="url(#tank-fill)"
      />
      <line
        x1={pad}
        x2={pad + innerW}
        y1={fillY}
        y2={fillY}
        stroke="#e2e8f0"
        stroke-opacity="0.25"
        stroke-width="1"
      />
    </g>

    <!-- 25/50/75% tick marks -->
    {#each [25, 50, 75] as t}
      {@const ty = pad + innerH - (innerH * t) / 100}
      <line
        x1={pad}
        x2={pad + 12}
        y1={ty}
        y2={ty}
        stroke="#334155"
        stroke-width="1"
      />
      <line
        x1={pad + innerW - 12}
        x2={pad + innerW}
        y1={ty}
        y2={ty}
        stroke="#334155"
        stroke-width="1"
      />
    {/each}

    <!-- centred percentage + litres -->
    <text
      x={w / 2}
      y={h / 2 - 6}
      text-anchor="middle"
      font-family="JetBrains Mono, monospace"
      font-size="32"
      font-weight="700"
      style="fill: rgb(var(--text-default)); paint-order: stroke; stroke: rgb(var(--bg-panel)); stroke-width: 4px;"
    >
      {pct.toFixed(0)}%
    </text>
    {#if litres != null}
      <text
        x={w / 2}
        y={h / 2 + 18}
        text-anchor="middle"
        font-family="JetBrains Mono, monospace"
        font-size="13"
        style="fill: rgb(var(--text-muted)); paint-order: stroke; stroke: rgb(var(--bg-panel)); stroke-width: 4px;"
      >
        {Math.round(litres)} L{capacity ? ` / ${Math.round(capacity)}` : ""}
      </text>
    {/if}
  </svg>

  <!-- 10-bar vertical gauge per mockup -->
  <div class="flex w-6 flex-col-reverse gap-[3px] py-1">
    {#each Array(10) as _, i}
      {@const lit = i < computedBars}
      <div
        class="flex-1 rounded-sm"
        class:bg-brand-blue={lit && i >= 2}
        class:bg-brand-amber={lit && i === 1}
        class:bg-brand-red={lit && i === 0}
        class:bg-border-strong={!lit}
        class:opacity-100={lit}
        class:opacity-25={!lit}
      ></div>
    {/each}
  </div>
</div>
