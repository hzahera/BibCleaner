export const API_ENDPOINT = "/api/clean-bib";
export const DEFAULT_INPUT_FILENAME = "bibliography.bib";
export const DEFAULT_DOWNLOAD_FILENAME = "cleaned.bib";
export const ACCEPTED_BIB_CONTENT_TYPE = "application/x-bibtex";
export const OUTPUT_BIB_CONTENT_TYPE = "text/x-bibtex;charset=utf-8";

export function ensureBibFilename(filename: string | undefined | null): string {
    const trimmed = (filename ?? "").trim();

    if (!trimmed) {
        return DEFAULT_INPUT_FILENAME;
    }

    if (trimmed.toLowerCase().endsWith(".bib")) {
        return trimmed;
    }

    const base = trimmed.replace(/\.[^.]+$/u, "") || "bibliography";
    return `${base}.bib`;
}

export function normalizeBibText(text: string): string {
    return text.replace(/\r\n?/gu, "\n");
}

export function createBibUploadFile(text: string, filename?: string | null): File {
    return new File([normalizeBibText(text)], ensureBibFilename(filename), {
        type: ACCEPTED_BIB_CONTENT_TYPE,
    });
}

export async function readFileAsBibFile(file: File): Promise<File> {
    return createBibUploadFile(await file.text(), file.name);
}

export function parseFilenameFromContentDisposition(
    value: string | null,
): string | null {
    if (!value) {
        return null;
    }

    const utf8Match = value.match(/filename\*=UTF-8''([^;]+)/i);
    if (utf8Match?.[1]) {
        try {
            return ensureBibFilename(decodeURIComponent(utf8Match[1]));
        } catch {
            return ensureBibFilename(utf8Match[1]);
        }
    }

    const filenameMatch = value.match(/filename="?([^";]+)"?/i);
    return filenameMatch?.[1] ? ensureBibFilename(filenameMatch[1]) : null;
}

export function deriveDownloadFilename(sourceFilename: string | null | undefined): string {
    const base = ensureBibFilename(sourceFilename);
    return `cleaned_${base}`;
}

export function createDownloadBlob(text: string): Blob {
    return new Blob([normalizeBibText(text)], { type: OUTPUT_BIB_CONTENT_TYPE });
}

function isHtmlErrorBody(response: Response, body: string): boolean {
    const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";
    if (contentType.includes("text/html")) {
        return true;
    }

    return /^<!doctype\s+html|^<html[\s>]/iu.test(body);
}

export async function responseErrorMessage(response: Response): Promise<string> {
    const rawBody = await response.text();
    const trimmedBody = rawBody.trim();

    if (trimmedBody) {
        if (isHtmlErrorBody(response, trimmedBody)) {
            if (response.status === 504) {
                return "Gateway timeout while waiting for API. Please try again with a smaller file or retry in a moment.";
            }

            return `Request failed with status ${response.status}`;
        }

        try {
            const payload = JSON.parse(trimmedBody) as { detail?: unknown };
            if (typeof payload.detail === "string" && payload.detail.trim()) {
                return payload.detail;
            }
        } catch {
            // Ignore parse errors and keep the raw text fallback.
        }

        return trimmedBody;
    }

    return `Request failed with status ${response.status}`;
}