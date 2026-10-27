/**
 * Requests to the API that change things, with the API's reasons for
 * refusing them turned into readable errors.
 */

/** The reason the API gives for refusing something, readably. */
async function refusal(response: Response, what: string): Promise<Error> {
	try {
		const body = (await response.json()) as { detail?: unknown };
		const { detail } = body;
		if (typeof detail === 'string') return new Error(detail);
		if (Array.isArray(detail)) {
			// Validation errors: say what each one is about.
			const messages = detail.map((d: { msg?: string; loc?: unknown[] }) => {
				const field = d.loc?.filter((l) => typeof l === 'string' && l !== 'body').join(' ');
				return field ? `${field}: ${d.msg}` : String(d.msg);
			});
			return new Error(messages.join('; '));
		}
	} catch {
		// Not JSON; fall through to the status.
	}
	return new Error(`${what} answered ${response.status}`);
}

/**
 * Send a request to the API.
 *
 * @param method - HTTP method.
 * @param url - Path under the API.
 * @param body - JSON body, if any.
 * @returns The answer's JSON body, or undefined for 204 No Content.
 * @throws Error with the API's reason when it refuses.
 */
export async function send<T>(method: string, url: string, body?: unknown): Promise<T> {
	const response = await fetch(url, {
		method,
		...(body === undefined
			? {}
			: { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
	});
	if (!response.ok) throw await refusal(response, `${method} ${url}`);
	return (response.status === 204 ? undefined : await response.json()) as T;
}
