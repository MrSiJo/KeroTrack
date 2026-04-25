<script lang="ts">
  type Props = {
    percentage: number;
    lengthCm?: number;
    heightCm?: number;
  };
  let { percentage, lengthCm = 178.5, heightCm = 137 }: Props = $props();

  const w = 220;
  const h = Math.round((heightCm / lengthCm) * w);
  const fillH = Math.max(0, Math.min(100, percentage)) / 100;
</script>

<svg
  viewBox={`0 0 ${w} ${h}`}
  class="block"
  role="img"
  aria-label={`Tank ${percentage}% full`}
>
  <defs>
    <linearGradient id="tank-fill" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0%" stop-color="#3b82f6" stop-opacity="0.7" />
      <stop offset="100%" stop-color="#1e3a8a" stop-opacity="0.95" />
    </linearGradient>
  </defs>
  <rect
    x="2"
    y="2"
    width={w - 4}
    height={h - 4}
    rx="10"
    ry="10"
    fill="#0f172a"
    stroke="#334155"
    stroke-width="2"
  />
  <rect
    x="6"
    y={6 + (h - 12) * (1 - fillH)}
    width={w - 12}
    height={(h - 12) * fillH}
    rx="6"
    fill="url(#tank-fill)"
  />
  <text
    x={w / 2}
    y={h / 2 + 4}
    text-anchor="middle"
    fill="#e2e8f0"
    font-family="JetBrains Mono, monospace"
    font-size="20"
    font-weight="600"
  >
    {percentage.toFixed(0)}%
  </text>
</svg>
