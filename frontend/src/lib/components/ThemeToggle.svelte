<script lang="ts">
  import { theme } from "$lib/stores/theme";
</script>

<button
  class="rounded border border-border px-2 py-1 text-xs text-text-muted hover:text-brand-blue"
  on:click={() => theme.toggle()}
  aria-label="Toggle theme"
>
  {$theme === "dark" ? "Light" : "Dark"}
</button>
