import { beforeEach, describe, expect, it, vi } from "vitest";
import { BibCleanerApp } from "./app";
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
        document.body.innerHTML = '<div id="app"></div>';
    });

    it("renders the two-panel layout and wiring", () => {
        const app = new BibCleanerApp({ document, fetchImpl: vi.fn(), apiBase: "/api" });
        const root = app.mount(document.getElementById("app") as HTMLElement);

        expect(root.querySelector("header h1")?.textContent).toBe("BibCleaner");
        expect(root.querySelectorAll(".panel")).toHaveLength(2);
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

        // create -> poll -> result
        const createCall = fetchMock.mock.calls.find(([url, init]) => url === "/api/jobs" && init?.method === "POST");
        expect(createCall).toBeTruthy();
        const formData = createCall?.[1]?.body as FormData;
        const uploaded = formData.get("file") as File;
        expect(uploaded.name).toBe("refs.bib");
        expect(uploaded.type).toBe("application/x-bibtex");

        expect(fetchMock.mock.calls.some(([url]) => url === "/api/jobs/j1")).toBe(true);
        expect(fetchMock.mock.calls.some(([url]) => url === "/api/jobs/j1/result")).toBe(true);

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

        const createCall = fetchMock.mock.calls.find(([url, init]) => url === "/api/jobs" && init?.method === "POST");
        const formData = createCall?.[1]?.body as FormData;
        const uploaded = formData.get("file") as File;
        expect(uploaded.name).toBe("bibliography.bib");
        expect((document.querySelector("[data-role='output-textarea']") as HTMLTextAreaElement).value)
            .toContain("Typed");
    });

    it("surfaces a job error to the user", async () => {
        const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
            if (url.endsWith("/jobs") && init?.method === "POST") {
                return Promise.resolve(jsonResponse({ job_id: "j1" }, { status: 202 }));
            }
            if (url.endsWith("/jobs/j1")) {
                return Promise.resolve(jsonResponse({ status: "error", error: "No BibTeX entries found" }));
            }
            throw new Error(`unexpected request: ${url}`);
        });
        const app = new BibCleanerApp({ document, fetchImpl: fetchMock, apiBase: "/api", pollIntervalMs: 0 });

        app.mount(document.getElementById("app") as HTMLElement);
        const input = document.querySelector("[data-role='input-textarea']") as HTMLTextAreaElement;
        input.value = "not bibtex";
        await app.submitCurrentContent();

        const status = document.querySelector(".status-message") as HTMLParagraphElement;
        expect(status.dataset.state).toBe("error");
        expect(status.textContent).toContain("No BibTeX entries found");
    });

    it("shows a loading indicator only while submit is in progress", async () => {
        let resolveCreate!: (response: Response) => void;
        const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
            if (url.endsWith("/jobs") && init?.method === "POST") {
                return new Promise<Response>((resolve) => {
                    resolveCreate = resolve;
                });
            }
            if (url.endsWith("/jobs/j1")) {
                return Promise.resolve(jsonResponse({ status: "done", done: 1, total: 1 }));
            }
            return Promise.resolve(textResponse("@article{demo,title={Typed}}\n"));
        });
        const app = new BibCleanerApp({ document, fetchImpl: fetchMock, apiBase: "/api", pollIntervalMs: 0 });

        app.mount(document.getElementById("app") as HTMLElement);
        const input = document.querySelector("[data-role='input-textarea']") as HTMLTextAreaElement;
        const cleanButton = document.querySelector("[data-action='clean']") as HTMLButtonElement;
        const indicator = document.querySelector("[data-role='processing-indicator']") as HTMLSpanElement;

        input.value = "@article{typed,title={Example}}";
        const pending = app.submitCurrentContent();

        expect(cleanButton.disabled).toBe(true);
        expect(indicator.hidden).toBe(false);
        expect(indicator.textContent).toContain("Processing...");

        resolveCreate(jsonResponse({ job_id: "j1" }, { status: 202 }));
        await pending;

        expect(cleanButton.disabled).toBe(false);
        expect(indicator.hidden).toBe(true);
    });

    it("downloads the current output using the latest filename", async () => {
        const fetchMock = jobFetch({ filename: "cleaned_refs.bib" });
        const clickMock = vi.fn();
        const createObjectUrlMock = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:123");
        const revokeObjectUrlMock = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
        const anchor = document.createElement("a");
        Object.defineProperty(anchor, "click", { value: clickMock });
        const createElementSpy = vi.spyOn(document, "createElement").mockImplementation((tagName: string) => {
            if (tagName.toLowerCase() === "a") {
                return anchor;
            }
            return document.createElementNS("http://www.w3.org/1999/xhtml", tagName) as HTMLElement;
        });

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
});
