// A client-only single-page app: the one page is prerendered as an empty
// shell that the browser fills from the API. Prerendered, its asset paths are
// relative, so it works wherever it is served from.
export const ssr = false;
export const prerender = true;
