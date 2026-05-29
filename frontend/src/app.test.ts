import { beforeEach, describe, expect, it, vi } from "vitest";
import { BibCleanerApp } from "./app";
import {
    createBibUploadFile,
    createDownloadBlob,
    deriveDownloadFilename,
    parseFilenameFromContentDisposition,
    responseErrorMessage,
} from "./helpers";

function createResponse(
    body: string,
    init: { ok?: boolean; status?: number; headers?: Record<string, string> } = {},
) {
    const headers = new Headers(init.headers ?? {});
    return {
        ok: init.ok ?? true,
        status: init.status ?? 200,
        headers,
        text: vi.fn().mockResolvedValue(body),
        json: vi.fn().mockRejectedValue(new Error("not json")),
    } as unknown as Response;
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
            {
                status: 504,
                headers: { "content-type": "text/html" },
            },
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
        const app = new BibCleanerApp({
            document,
            fetchImpl: vi.fn(),
            apiEndpoint: "/api/clean-bib",
        });

        const root = app.mount(document.getElementById("app") as HTMLElement);

        expect(root.querySelector("header h1")?.textContent).toBe("BibCleaner");
        expect(root.querySelectorAll(".panel")).toHaveLength(2);
        expect(root.querySelector("[data-action='upload']")).toBeTruthy();
        expect(root.querySelector("[data-action='clean']")).toBeTruthy();
        expect(root.querySelector("[data-action='download']")).toBeTruthy();
        expect(root.querySelector("[data-role='output-textarea']") as HTMLTextAreaElement).toBeTruthy();
    });

    it("uploads a file, submits it to the API, and populates the output", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            createResponse("@article{demo,title={Cleaned}}\n", {
                headers: { "content-disposition": 'attachment; filename="cleaned_refs.bib"' },
            }),
        );
        const app = new BibCleanerApp({ document, fetchImpl: fetchMock, apiEndpoint: "/api/clean-bib" });

        app.mount(document.getElementById("app") as HTMLElement);
        await app.loadFile(new File(["@article{demo,title={Raw}}"], "refs.txt", { type: "text/plain" }));

        expect(fetchMock).toHaveBeenCalledTimes(1);
        const [url, init] = fetchMock.mock.calls[0];
        expect(url).toBe("/api/clean-bib");
        expect(init?.method).toBe("POST");

        const formData = init?.body as FormData;
        const uploaded = formData.get("file") as File;
        expect(uploaded.name).toBe("refs.bib");
        expect(uploaded.type).toBe("application/x-bibtex");

        expect((document.querySelector("[data-role='input-textarea']") as HTMLTextAreaElement).value)
            .toContain("@article{demo,title={Raw}}");
        expect((document.querySelector("[data-role='output-textarea']") as HTMLTextAreaElement).value)
            .toContain("Cleaned");
        expect(document.querySelector(".status-message")?.textContent).toContain("successfully");
    });

    it("submits typed content through the explicit clean action", async () => {
        const fetchMock = vi.fn().mockResolvedValue(createResponse("@article{demo,title={Typed}}\n"));
        const app = new BibCleanerApp({ document, fetchImpl: fetchMock, apiEndpoint: "/api/clean-bib" });

        app.mount(document.getElementById("app") as HTMLElement);

        const input = document.querySelector("[data-role='input-textarea']") as HTMLTextAreaElement;
        input.value = "@article{typed,title={Example}}";

        await app.submitCurrentContent();

        expect(fetchMock).toHaveBeenCalledTimes(1);
        const formData = fetchMock.mock.calls[0][1]?.body as FormData;
        const uploaded = formData.get("file") as File;
        expect(uploaded.name).toBe("bibliography.bib");
        expect((document.querySelector("[data-role='output-textarea']") as HTMLTextAreaElement).value)
            .toContain("Typed");
    });

    it("shows a loading indicator only while submit is in progress", async () => {
        let resolveResponse: ((response: Response) => void) | null = null;
        const fetchMock = vi.fn().mockImplementation(
            () =>
                new Promise<Response>((resolve) => {
                    resolveResponse = resolve;
                }),
        );
        const app = new BibCleanerApp({ document, fetchImpl: fetchMock, apiEndpoint: "/api/clean-bib" });

        app.mount(document.getElementById("app") as HTMLElement);

        const input = document.querySelector("[data-role='input-textarea']") as HTMLTextAreaElement;
        const cleanButton = document.querySelector("[data-action='clean']") as HTMLButtonElement;
        const indicator = document.querySelector("[data-role='processing-indicator']") as HTMLSpanElement;

        input.value = "@article{typed,title={Example}}";

        const pendingSubmit = app.submitCurrentContent();

        expect(cleanButton.disabled).toBe(true);
        expect(indicator.hidden).toBe(false);
        expect(indicator.textContent).toContain("Processing...");

        resolveResponse?.(createResponse("@article{demo,title={Typed}}\n") as unknown as Response);
        await pendingSubmit;

        expect(cleanButton.disabled).toBe(false);
        expect(indicator.hidden).toBe(true);
    });

    it("downloads the current output using the latest filename", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            createResponse("@article{demo,title={Cleaned}}\n", {
                headers: { "content-disposition": 'attachment; filename="cleaned_refs.bib"' },
            }),
        );
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

        const app = new BibCleanerApp({ document, fetchImpl: fetchMock, apiEndpoint: "/api/clean-bib" });
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