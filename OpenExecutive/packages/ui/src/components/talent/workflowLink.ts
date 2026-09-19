/** Build a /jobs/{name} link with a base64url-encoded `?prefill=` payload.
 *
 * Mirrors the decoder in app/jobs/[name]/page.tsx (UTF-8 bytes → base64url).
 * Values must be strings — the jobs form only applies string prefill values. */
export function workflowLink(name: string, prefill: Record<string, string>): string {
  const json = JSON.stringify(prefill);
  const bytes = new TextEncoder().encode(json);
  let binary = "";
  bytes.forEach((b) => {
    binary += String.fromCharCode(b);
  });
  const b64 = btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `/jobs/${name}?prefill=${b64}`;
}
