<script lang="ts">
  import { goto } from "$app/navigation";
  import { auth } from "$lib/stores/auth";
  import { ApiError } from "$lib/api";

  let username = $state("");
  let password = $state("");
  let submitting = $state(false);
  let error = $state<string | null>(null);

  async function submit(e: Event) {
    e.preventDefault();
    error = null;
    submitting = true;
    try {
      await auth.login(username, password);
      goto("/");
    } catch (err) {
      error = err instanceof ApiError ? err.message : (err as Error).message;
    } finally {
      submitting = false;
    }
  }
</script>

<form
  class="w-full max-w-sm rounded-lg border border-border bg-bg-panel p-6"
  on:submit={submit}
>
  <h1 class="text-lg font-semibold text-text">KeroTrack login</h1>
  <p class="mt-1 text-xs text-text-subtle">Single-user · v2</p>

  <label class="mt-6 block text-xs text-text-muted">
    Username
    <input
      type="text"
      class="mt-1 w-full rounded border border-border bg-bg-elev px-2 py-1.5 text-sm text-text"
      bind:value={username}
      autocomplete="username"
      required
    />
  </label>

  <label class="mt-3 block text-xs text-text-muted">
    Password
    <input
      type="password"
      class="mt-1 w-full rounded border border-border bg-bg-elev px-2 py-1.5 text-sm text-text"
      bind:value={password}
      autocomplete="current-password"
      required
    />
  </label>

  {#if error}
    <p class="mt-3 text-xs text-brand-red">{error}</p>
  {/if}

  <button
    type="submit"
    class="mt-5 w-full rounded bg-brand-blue px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-blue-2 disabled:opacity-60"
    disabled={submitting}
  >
    {submitting ? "Signing in…" : "Sign in"}
  </button>
</form>
