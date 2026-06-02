import { beforeEach, describe, expect, it, vi } from "vitest";
import { BibCleanerApp } from "./app";
import logoUrl from "../logo.png";
import upbLogoUrl from "../UPB.png";
import diceLogoUrl from "../DICE.png";
import {
    createBibUploadFile,
    createDownloadBlob,
    deriveDownloadFilename,
    parseFilenameFromContentDisposition,
    responseErrorMessage,
} from "./helpers";

function jsonResponse(
    payload: unknown,
    init: { ok?: boolean; status?: number; headers?: Record<string, string> } = {},
) {
    return {
        ok: init.ok ?? true,
        status: init.status ?? 200,
        headers: new Headers(init.headers ?? {}),
        json: vi.fn().mockResolvedValue(payload),
        text: vi.fn().mockResolvedValue(JSON.stringify(payload)),
    } as unknown as Response;
}

function textResponse(
    body: string,
    init: { ok?: boolean; status?: number; headers?: Record<string, string> } = {},
) {
    return {
        ok: init.ok ?? true,
        status: init.status ?? 200,
        headers: new Headers(init.headers ?? {}),
        text: vi.fn().mockResolvedValue(body),
        json: vi.fn().mockRejectedValue(new Error("not json")),
    } as unknown as Response;
}

function createJsonResponse(
    payload: unknown,
    init: { ok?: boolean; status?: number; headers?: Record<string, string> } = {},
) {
    const headers = new Headers(init.headers ?? {});
    return {
        ok: init.ok ?? true,
        status: init.status ?? 200,
        headers,
        text: vi.fn().mockRejectedValue(new Error("not text")),
        json: vi.fn().mockResolvedValue(payload),
    } as unknown as Response;
}

function findCall(
    calls: unknown[][],
    predicate: (url: string, init?: RequestInit) => boolean,
): [string, RequestInit | undefined] | undefined {
    for (const call of calls) {
        const [url, init] = call as [string, RequestInit | undefined];
        if (predicate(url, init)) {
            return [url, init];
        }
    }

    return undefined;
}

function hasCall(
    calls: unknown[][],
    predicate: (url: string, init?: RequestInit) => boolean,
): boolean {
    return findCall(calls, predicate) !== undefined;
}

/** A fetch mock that walks the create -> poll -> result job flow. */
function jobFetch(opts: { cleaned?: string; filename?: string | null; jobId?: string } = {}) {
    const { cleaned = "@article{demo,title={Cleaned}}\n", filename = "cleaned_refs.bib", jobId = "j1" } = opts;
    return vi.fn().mockImplementation((url: string, init?: RequestInit) => {
        if (url.endsWith("/jobs") && init?.method === "POST") {
            return Promise.resolve(jsonResponse({ job_id: jobId, status: "queued" }, { status: 202 }));
        }
        if (url.endsWith(`/jobs/${jobId}`)) {
            return Promise.resolve(jsonResponse({ status: "done", done: 1, total: 1 }));
        }
        if (url.endsWith(`/jobs/${jobId}/result`)) {
            return Promise.resolve(
                textResponse(cleaned, {
                    headers: filename ? { "content-disposition": `attachment; filename="${filename}"` } : {},
                }),
            );
        }
        if (url.endsWith("/validation")) {
            return Promise.resolve(createJsonResponse([]));
        }
        throw new Error(`unexpected request: ${url}`);
    });
}

describe("BibCleaner frontend helpers", () => {
    it("derives download filenames from content disposition headers", () => {
        expect(
            parseFilenameFromContentDisposition('attachment; filename="cleaned_refs.bib"'),
        ).toBe("cleaned_refs.bib");
        expect(deriveDownloadFilename("notes.txt")).toBe("cleaned_notes.bib");
    });

    it("creates a bib download blob with the expected content type", () => {
        const blob = createDownloadBlob("@article{demo}");
        expect(blob.type).toBe("text/x-bibtex;charset=utf-8");
    });

    it("normalizes uploaded content into an accepted bib file", async () => {
        const file = createBibUploadFile("@article{demo}", "paper.txt");
        expect(file.name).toBe("paper.bib");
        expect(file.type).toBe("application/x-bibtex");
        expect(await file.text()).toContain("@article{demo}");
    });

    it("returns plain text fallback messages from error responses", async () => {
        const response = new Response("Backend unavailable", {
            status: 503,
            headers: { "content-type": "text/plain" },
        });
        await expect(responseErrorMessage(response)).resolves.toBe("Backend unavailable");
    });

    it("maps HTML 504 gateway errors to a concise timeout message", async () => {
        const response = new Response(
            "<!DOCTYPE html><html><body><h1>504 Gateway Time-out</h1></body></html>",
            { status: 504, headers: { "content-type": "text/html" } },
        );
        await expect(responseErrorMessage(response)).resolves.toBe(
            "Gateway timeout while waiting for API. Please try again with a smaller file or retry in a moment.",
        );
    });
});

describe("BibCleaner frontend app", () => {
    beforeEach(() => {
        vi.restoreAllMocks();
        document.body.innerHTML = '<div id="app"></div>';
    });

    it("renders the two-panel layout and wiring", () => {
        const app = new BibCleanerApp({ document, fetchImpl: vi.fn(), apiBase: "/api" });
        const root = app.mount(document.getElementById("app") as HTMLElement);

        const logos = root.querySelectorAll("img");
        expect(logos).toHaveLength(3);
        expect(logos[0]?.getAttribute("alt")).toBe("BibCleaner Logo");
        expect(logos[0]?.getAttribute("src")).toBe(logoUrl);
        expect(root.querySelectorAll(".panel")).toHaveLength(2);
        const supportedBy = root.querySelector("#supported-by-title");
        expect(supportedBy?.textContent).toBe("Supported By");
        expect(logos[1]?.getAttribute("alt")).toBe("UPB logo");
        expect(logos[1]?.getAttribute("src")).toBe(upbLogoUrl);
        expect(logos[2]?.getAttribute("alt")).toBe("DICE logo");
        expect(logos[2]?.getAttribute("src")).toBe(diceLogoUrl);
        expect(root.querySelector("[data-action='upload']")).toBeTruthy();
        expect(root.querySelector("[data-action='clean']")).toBeTruthy();
        expect(root.querySelector("[data-action='download']")).toBeTruthy();
        expect(root.querySelector("[data-role='output-textarea']")).toBeTruthy();
    });

    it("uploads a file, runs the job flow, and populates the output", async () => {
        const fetchMock = jobFetch();
        const app = new BibCleanerApp({ document, fetchImpl: fetchMock, apiBase: "/api", pollIntervalMs: 0 });

        app.mount(document.getElementById("app") as HTMLElement);
        await app.loadFile(new File(["@article{demo,title={Raw}}"], "refs.bib", { type: "application/x-bibtex" }));

        const createCall = findCall(
            fetchMock.mock.calls as unknown[][],
            (url, init) => url === "/api/jobs" && init?.method === "POST",
        );
        expect(createCall).toBeTruthy();
        const formData = createCall?.[1]?.body as FormData;
        const uploaded = formData.get("file") as File;
        expect(uploaded.name).toBe("refs.bib");
        expect(uploaded.type).toBe("application/x-bibtex");

        expect(hasCall(fetchMock.mock.calls as unknown[][], (url) => url === "/api/jobs/j1")).toBe(true);
        expect(hasCall(fetchMock.mock.calls as unknown[][], (url) => url === "/api/jobs/j1/result")).toBe(true);

        expect((document.querySelector("[data-role='input-textarea']") as HTMLTextAreaElement).value)
            .toContain("@article{demo,title={Raw}}");
        expect((document.querySelector("[data-role='output-textarea']") as HTMLTextAreaElement).value)
            .toContain("Cleaned");
        expect(document.querySelector(".status-message")?.textContent).toContain("successfully");
    });

    it("submits typed content through the explicit clean action", async () => {
        const fetchMock = jobFetch({ cleaned: "@article{demo,title={Typed}}\n", filename: null });
        const app = new BibCleanerApp({ document, fetchImpl: fetchMock, apiBase: "/api", pollIntervalMs: 0 });

        app.mount(document.getElementById("app") as HTMLElement);
        const input = document.querySelector("[data-role='input-textarea']") as HTMLTextAreaElement;
        input.value = "@article{typed,title={Example}}";

        await app.submitCurrentContent();

        const createCall = findCall(
            fetchMock.mock.calls as unknown[][],
            (url, init) => url === "/api/jobs" && init?.method === "POST",
        );
        const formData = createCall?.[1]?.body as FormData;
        const uploaded = formData.get("file") as File;
        expect(uploaded.name).toBe("bibliography.bib");
        expect((document.querySelector("[data-role='output-textarea']") as HTMLTextAreaElement).value)
            .toContain("Typed");
    });

    it("updates spinner text while moving from processing to validation", async () => {
        const validationState: { resolve?: (response: Response) => void } = {};
        const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
            if (url === "/api/jobs" && init?.method === "POST") {
                return Promise.resolve(jsonResponse({ job_id: "j1", status: "queued" }, { status: 202 }));
            }
            if (url === "/api/jobs/j1") {
                return Promise.resolve(jsonResponse({ status: "done", done: 1, total: 1 }));
            }
            if (url === "/api/jobs/j1/result") {
                return Promise.resolve(textResponse("@article{demo,title={Typed}}\n"));
            }
            if (url === "/api/custom-validation") {
                return new Promise<Response>((resolve) => {
                    validationState.resolve = resolve;
                });
            }
            throw new Error(`unexpected request: ${url}`);
        });

        const app = new BibCleanerApp({
            document,
            fetchImpl: fetchMock,
            apiBase: "/api",
            validationEndpoint: "/api/custom-validation",
            pollIntervalMs: 0,
        });

        app.mount(document.getElementById("app") as HTMLElement);
        const input = document.querySelector("[data-role='input-textarea']") as HTMLTextAreaElement;
        const uploadButton = document.querySelector("[data-action='upload']") as HTMLButtonElement;
        const cleanButton = document.querySelector("[data-action='clean']") as HTMLButtonElement;
        const downloadButton = document.querySelector("[data-action='download']") as HTMLButtonElement;
        const indicator = document.querySelector("[data-role='processing-indicator']") as HTMLSpanElement;
        input.value = "@article{typed,title={Example}}";

        const pending = app.submitCurrentContent();

        expect(uploadButton.disabled).toBe(true);
        expect(cleanButton.disabled).toBe(true);
        expect(downloadButton.disabled).toBe(true);
        expect(indicator.hidden).toBe(false);
        expect(indicator.textContent).toContain("Processing bibliography...");

        await Promise.resolve();
        await Promise.resolve();
        expect(indicator.textContent).toContain("Validating output...");

        const resolveValidation = validationState.resolve;
        if (!resolveValidation) {
            throw new Error("validation resolver was not captured");
        }
        resolveValidation(createJsonResponse([]));
        await pending;

        expect(uploadButton.disabled).toBe(false);
        expect(cleanButton.disabled).toBe(false);
        expect(downloadButton.disabled).toBe(false);
        expect(indicator.hidden).toBe(true);
    });

    it("surfaces a job error to the user and clears busy state", async () => {
        const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
            if (url === "/api/jobs" && init?.method === "POST") {
                return Promise.resolve(jsonResponse({ job_id: "j1" }, { status: 202 }));
            }
            if (url === "/api/jobs/j1") {
                return Promise.resolve(
                    jsonResponse({ status: "error", error: "No BibTeX entries found" }),
                );
            }
            throw new Error(`unexpected request: ${url}`);
        });
        const app = new BibCleanerApp({ document, fetchImpl: fetchMock, apiBase: "/api", pollIntervalMs: 0 });

        app.mount(document.getElementById("app") as HTMLElement);
        const input = document.querySelector("[data-role='input-textarea']") as HTMLTextAreaElement;
        const cleanButton = document.querySelector("[data-action='clean']") as HTMLButtonElement;
        const indicator = document.querySelector("[data-role='processing-indicator']") as HTMLSpanElement;
        input.value = "not bibtex";

        await app.submitCurrentContent();

        const status = document.querySelector(".status-message") as HTMLParagraphElement;
        expect(status.dataset.state).toBe("error");
        expect(status.textContent).toContain("No BibTeX entries found");
        expect(cleanButton.disabled).toBe(false);
        expect(indicator.hidden).toBe(true);
    });

    it("renders validation dropdown content when validation returns results", async () => {
        const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
            if (url === "/api/jobs" && init?.method === "POST") {
                return Promise.resolve(jsonResponse({ job_id: "j1" }, { status: 202 }));
            }
            if (url === "/api/jobs/j1") {
                return Promise.resolve(jsonResponse({ status: "done", done: 1, total: 1 }));
            }
            if (url === "/api/jobs/j1/result") {
                return Promise.resolve(textResponse("@article{demo,title={Cleaned}}\n"));
            }
            if (url === "/api/validation") {
                return Promise.resolve(
                    createJsonResponse([
                        {
                            entry_id: "demo",
                            errors: ["author"],
                            warnings: ["doi", "url"],
                        },
                    ]),
                );
            }
            throw new Error(`unexpected request: ${url}`);
        });
        const app = new BibCleanerApp({ document, fetchImpl: fetchMock, apiBase: "/api", pollIntervalMs: 0 });

        app.mount(document.getElementById("app") as HTMLElement);
        const input = document.querySelector("[data-role='input-textarea']") as HTMLTextAreaElement;
        input.value = "@article{demo,title={Example}}";

        await app.submitCurrentContent();

        const validationContainer = document.querySelector(
            "[data-role='validation-results']",
        ) as HTMLElement;
        expect(validationContainer.hidden).toBe(false);
        expect(document.querySelector("[data-role='validation-summary']")?.textContent).toContain(
            "Validation results",
        );
        expect(document.querySelector("[data-role='validation-content']")?.textContent).toContain(
            "demo",
        );
        expect(document.querySelector("[data-role='validation-content']")?.textContent).toContain(
            "Missing required: author",
        );
        expect(document.querySelector("[data-role='validation-content']")?.textContent).toContain(
            "Missing optional: doi, url",
        );
    });

    it("downloads the current output using the latest filename", async () => {
        const fetchMock = jobFetch({ filename: "cleaned_refs.bib" });
        const clickMock = vi.fn();
        const createObjectUrlMock = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:123");
        const revokeObjectUrlMock = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
        const originalCreateElement = document.createElement.bind(document);
        const anchor = originalCreateElement("a");
        Object.defineProperty(anchor, "click", { value: clickMock });
        const createElementSpy = vi.spyOn(document, "createElement").mockImplementation(
            ((tagName: string, options?: ElementCreationOptions) => {
                if (tagName.toLowerCase() === "a") {
                    return anchor;
                }

                return originalCreateElement(tagName, options);
            }) as typeof document.createElement,
        );

        const app = new BibCleanerApp({ document, fetchImpl: fetchMock, apiBase: "/api", pollIntervalMs: 0 });
        app.mount(document.getElementById("app") as HTMLElement);

        await app.loadFile(new File(["@article{demo,title={Raw}}"], "refs.bib", { type: "application/octet-stream" }));
        app.downloadCurrentOutput();

        expect(createObjectUrlMock).toHaveBeenCalledTimes(1);
        expect(anchor.download).toBe("cleaned_refs.bib");
        expect(clickMock).toHaveBeenCalledTimes(1);

        createObjectUrlMock.mockRestore();
        revokeObjectUrlMock.mockRestore();
        createElementSpy.mockRestore();
    });

    it("does not time out while the job keeps progressing", async () => {
        vi.useFakeTimers();
        const statuses: Array<{ status: string; done: number; total: number }> = [
            { status: "processing", done: 0, total: 4 },
            { status: "processing", done: 1, total: 4 },
            { status: "processing", done: 2, total: 4 },
            { status: "processing", done: 3, total: 4 },
            { status: "done", done: 4, total: 4 },
        ];
        let pollCount = 0;
        const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
            if (url === "/api/jobs" && init?.method === "POST") {
                return Promise.resolve(jsonResponse({ job_id: "j1" }, { status: 202 }));
            }
            if (url === "/api/jobs/j1") {
                const index = Math.min(pollCount, statuses.length - 1);
                pollCount += 1;
                return Promise.resolve(jsonResponse(statuses[index]));
            }
            if (url === "/api/jobs/j1/result") {
                return Promise.resolve(textResponse("@article{demo,title={Cleaned}}\n"));
            }
            if (url === "/api/validation") {
                return Promise.resolve(createJsonResponse([]));
            }
            throw new Error(`unexpected request: ${url}`);
        });

        const app = new BibCleanerApp({
            document,
            fetchImpl: fetchMock,
            apiBase: "/api",
            pollIntervalMs: 20,
            pollTimeoutMs: 50,
        });

        app.mount(document.getElementById("app") as HTMLElement);
        (document.querySelector("[data-role='input-textarea']") as HTMLTextAreaElement).value =
            "@article{demo,title={Input}}";

        const pending = app.submitCurrentContent();
        await Promise.resolve();

        for (let i = 0; i < 5; i += 1) {
            await vi.advanceTimersByTimeAsync(20);
        }
        await pending;

        expect((document.querySelector(".status-message") as HTMLParagraphElement).dataset.state)
            .toBe("success");
        expect((document.querySelector(".status-message") as HTMLParagraphElement).textContent)
            .toContain("successfully");

        vi.useRealTimers();
    });

    it("times out when the job remains stalled", async () => {
        vi.useFakeTimers();
        const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
            if (url === "/api/jobs" && init?.method === "POST") {
                return Promise.resolve(jsonResponse({ job_id: "j1" }, { status: 202 }));
            }
            if (url === "/api/jobs/j1") {
                return Promise.resolve(jsonResponse({ status: "processing", done: 0, total: 10 }));
            }
            throw new Error(`unexpected request: ${url}`);
        });

        const app = new BibCleanerApp({
            document,
            fetchImpl: fetchMock,
            apiBase: "/api",
            pollIntervalMs: 20,
            pollTimeoutMs: 60,
        });

        app.mount(document.getElementById("app") as HTMLElement);
        (document.querySelector("[data-role='input-textarea']") as HTMLTextAreaElement).value =
            "@article{demo,title={Input}}";

        const pending = app.submitCurrentContent();
        await Promise.resolve();

        for (let i = 0; i < 6; i += 1) {
            await vi.advanceTimersByTimeAsync(20);
        }
        await pending;

        const status = document.querySelector(".status-message") as HTMLParagraphElement;
        expect(status.dataset.state).toBe("error");
        expect(status.textContent).toContain("Timed out waiting for job progress");

        vi.useRealTimers();
    });
});
