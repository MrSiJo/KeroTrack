<script lang="ts">
  import { page } from "$app/state";
  import { auth } from "$lib/stores/auth";

  type NavItem = { href: string; label: string; chord: string };
  const items: NavItem[] = [
    { href: "/", label: "Dashboard", chord: "g d" },
    { href: "/trends", label: "Trends", chord: "g t" },
    { href: "/forecast", label: "Forecast", chord: "g f" },
    { href: "/costs", label: "Costs", chord: "g c" },
    { href: "/records", label: "Records", chord: "g r" },
    { href: "/mqtt", label: "MQTT", chord: "g m" },
    { href: "/settings", label: "Settings", chord: "g s" },
  ];

  function isActive(href: string): boolean {
    if (href === "/") return page.url.pathname === "/";
    return page.url.pathname.startsWith(href);
  }

  async function doLogout() {
    await auth.logout();
  }
</script>

<aside
  class="flex h-screen w-[220px] flex-col border-r border-border bg-bg-panel"
>
  <div class="px-5 py-5">
    <div class="font-semibold tracking-tight text-text">KeroTrack</div>
    <div class="text-xs text-text-subtle">v2</div>
  </div>

  <nav class="flex-1 space-y-1 px-2">
    {#each items as item (item.href)}
      <a
        href={item.href}
        class="flex items-center justify-between rounded px-3 py-1.5 text-sm transition"
        class:bg-bg-elev={isActive(item.href)}
        class:text-brand-blue={isActive(item.href)}
        class:border-l-2={isActive(item.href)}
        class:border-brand-blue={isActive(item.href)}
        class:text-text-muted={!isActive(item.href)}
      >
        <span>{item.label}</span>
        <span class="font-mono text-[10px] text-text-subtle">{item.chord}</span>
      </a>
    {/each}
  </nav>

  <div class="border-t border-border px-3 py-3 text-xs text-text-subtle">
    <div class="flex items-center justify-between">
      <span class="truncate">{$auth.user ?? "—"}</span>
      <button
        class="rounded border border-border px-2 py-0.5 text-text-muted hover:text-brand-blue"
        on:click={doLogout}
      >
        log out
      </button>
    </div>
  </div>
</aside>
