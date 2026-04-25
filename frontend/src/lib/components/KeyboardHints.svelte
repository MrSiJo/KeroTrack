<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";

  let chord = $state("");

  function clearChord() {
    chord = "";
  }

  function onKey(e: KeyboardEvent) {
    if (
      (e.target as HTMLElement | null)?.matches?.("input,textarea,select")
    ) {
      return;
    }
    if (e.key === "?") {
      alert(
        "Vim-style nav: g d / g t / g f / g c / g r / g m / g s — Dashboard, Trends, Forecast, Costs, Records, MQTT, Settings.",
      );
      return;
    }
    if (chord === "g") {
      const map: Record<string, string> = {
        d: "/",
        t: "/trends",
        f: "/forecast",
        c: "/costs",
        r: "/records",
        m: "/mqtt",
        s: "/settings",
      };
      const target = map[e.key];
      clearChord();
      if (target) {
        e.preventDefault();
        goto(target);
      }
      return;
    }
    if (e.key === "g") {
      chord = "g";
      setTimeout(clearChord, 1000);
    }
  }

  onMount(() => {
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
</script>
