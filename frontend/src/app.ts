import {
    VALIDATION_ENDPOINT,
    API_BASE,
    DEFAULT_DOWNLOAD_FILENAME,
    DEFAULT_INPUT_FILENAME,
    createBibUploadFile,
    createDownloadBlob,
    deriveDownloadFilename,
    parseFilenameFromContentDisposition,
    readFileAsBibFile,
    responseErrorMessage,
    normalizeBibText,
} from "./helpers";
import logoUrl from "../logo.png";
import upbLogoUrl from "../UPB.png";
import diceLogoUrl from "../DICE.png";

type FetchLike = typeof fetch;

interface ValidationResult {
    entry_id: string;
    errors: string[];
    warnings: string[];
}

interface JobStatus {
    status: string; // queued | processing | done | error
    done?: number;
    total?: number;
    error?: string;
}

interface AppElements {
    root: HTMLElement;
    status: HTMLParagraphElement;
    inputTextArea: HTMLTextAreaElement;
    outputTextArea: HTMLTextAreaElement;
    uploadButton: HTMLButtonElement;
    fileInput: HTMLInputElement;
    cleanButton: HTMLButtonElement;
    processingIndicator: HTMLSpanElement;
    processingIndicatorText: HTMLSpanElement;
    downloadButton: HTMLButtonElement;
    validationContainer: HTMLElement;
    validationDropdown: HTMLDetailsElement;
    validationSummary: HTMLElement;
    validationContent: HTMLElement;
}

export interface BibCleanerAppOptions {
    document?: Document;
    fetchImpl?: FetchLike;
    validationEndpoint?: string;
    apiBase?: string;
    pollIntervalMs?: number;
    pollTimeoutMs?: number;
}

interface JobProgressSnapshot {
    status: string;
    done: number | null;
    total: number | null;
}

export class BibCleanerApp {
    private readonly document: Document;
    private readonly fetchImpl: FetchLike;
    private readonly validationEndpoint: string;
    private readonly apiBase: string;
    private readonly pollIntervalMs: number;
    private readonly pollTimeoutMs: number;
    private elements: AppElements | null = null;
    private currentDownloadFilename = DEFAULT_DOWNLOAD_FILENAME;

    constructor(options: BibCleanerAppOptions = {}) {
        this.document = options.document ?? document;
        this.fetchImpl = options.fetchImpl ?? fetch.bind(globalThis);
        this.validationEndpoint = options.validationEndpoint ?? VALIDATION_ENDPOINT;
        this.apiBase = (options.apiBase ?? API_BASE).replace(/\/+$/u, "");
        this.pollIntervalMs = options.pollIntervalMs ?? 1000;
        this.pollTimeoutMs = options.pollTimeoutMs ?? 300000;
    }

    mount(container: HTMLElement): HTMLElement {
        const root = this.document.createElement("div");
        root.className = "app-shell";
        root.innerHTML = `
      <header class="app-header">
                <img src="${logoUrl}" alt="BibCleaner Logo"/>
      </header>
      <p class="status-message" role="alert" aria-live="polite"></p>
      <main class="app-main">
        <section class="panel panel--input" aria-label="Input bibliography">
          <div class="panel__toolbar">
            <label for="bib-input">Please, write or upload your .bib file</label>
            <div class="panel__actions">
              <button type="button" class="button--secondary" data-action="upload">Upload</button>
              <input class="visually-hidden" type="file" accept=".bib" data-role="file-input" />
            </div>
          </div>
          <textarea
            id="bib-input"
            data-role="input-textarea"
            spellcheck="false"
            autocomplete="off"
            autocapitalize="off"
            placeholder="Paste BibTeX here or upload a .bib file..."
          ></textarea>
          <div class="panel__options-checkbox">
            <fieldset>
                <legend>Options</legend>
                <span><input type="checkbox" id="protect_caps" name="protect_caps" checked/><label for="protect_caps">Title capitalization protection</label><span class="tooltip-container"><span class="tooltip-icon" aria-hidden="true">🛈</span><span class="tooltip-text" role="tooltip">Ensure the capitalization stays as in the input .bib file</span></span></span>
                <span><input type="checkbox" id="dedup" name="dedup" checked/><label for="dedup">Duplicate merging</label><span class="tooltip-container"><span class="tooltip-icon" aria-hidden="true">🛈</span><span class="tooltip-text" role="tooltip">Deduplicate entries based on their title and authors</span></span></span>
                <span><input type="checkbox" id="normalize_keys" name="normalize_keys" checked/><label for="normalize_keys">Normalize entry keys</label><span class="tooltip-container"><span class="tooltip-icon" aria-hidden="true">🛈</span><span class="tooltip-text" role="tooltip">Change the entries ID to a default format</span></span></span>
                <span><input type="checkbox" id="validate" name="validate" checked/><label for="validate">Validate bibliography</label><span class="tooltip-container"><span class="tooltip-icon" aria-hidden="true">🛈</span><span class="tooltip-text" role="tooltip">Check if the entries have the required and optional fields</span></span></span>
            </fieldset>
          </div>
          <div class="panel__submit-row">
            <button type="button" class="button--primary" data-action="clean">Clean bibliography</button>
                        <span
                            class="processing-indicator"
                            data-role="processing-indicator"
                            role="status"
                            aria-live="polite"
                            aria-label="Processing..."
                            hidden
                        >
                            <span class="processing-indicator__spinner" aria-hidden="true"></span>
                            <span class="processing-indicator__text">Processing...</span>
                        </span>
          </div>
        </section>
        <section class="panel panel--output" aria-label="Cleaned bibliography">
          <div class="panel__toolbar">
            <label for="bib-output">Please, copy or download your cleaned .bib file</label>
            <div class="panel__actions">
              <button type="button" class="button--secondary" data-action="download">Download</button>
            </div>
          </div>
          <textarea
            id="bib-output"
            data-role="output-textarea"
            spellcheck="false"
            readonly
            placeholder="Cleaned BibTeX will appear here..."
          ></textarea>
                    <section class="validation-results" data-role="validation-results" hidden>
                        <details class="validation-results__dropdown" data-role="validation-dropdown">
                            <summary class="validation-results__summary" data-role="validation-summary">Validation results</summary>
                            <div class="validation-results__content" data-role="validation-content"></div>
                        </details>
                    </section>
        </section>
        
      </main>
            <section class="support-section" aria-labelledby="supported-by-title">
                <div class="support-section__header">
                    <p class="support-section__eyebrow">Contributing Institutions</p>
                    <h2 id="supported-by-title" class="support-section__title">Supported By</h2>
                </div>
                <div class="support-section__logos" aria-label="Supporting institutions">
                    <a href="https://www.uni-paderborn.de/" target="_blank" rel="noopener">
                        <figure class="support-logo-card support-logo-card--upb">
                            <img src="${upbLogoUrl}" alt="UPB logo" class="support-logo support-logo--upb" />
                        </figure>
                    </a>
                    <a href="https://dice-research.org/" target="_blank" rel="noopener">
                        <figure class="support-logo-card support-logo-card--dice">
                            <img src="${diceLogoUrl}" alt="DICE logo" class="support-logo support-logo--dice" />
                        </figure>
                    </a>
                </div>
            </section>
    `;

        container.replaceChildren(root);

        const elements = this.queryElements(root);
        this.elements = elements;

        elements.uploadButton.addEventListener("click", () => {
            elements.fileInput.click();
        });

        elements.fileInput.addEventListener("change", async () => {
            const file = elements.fileInput.files?.[0] ?? null;
            elements.fileInput.value = "";
            if (file) {
                await this.loadFile(file);
            }
        });

        elements.cleanButton.addEventListener("click", async () => {
            await this.submitCurrentContent();
        });

        elements.downloadButton.addEventListener("click", () => {
            this.downloadCurrentOutput();
        });

        return root;
    }

    async loadFile(file: File): Promise<void> {
        if (!file.name.toLowerCase().endsWith(".bib")) {
            this.showError("Only .bib files are accepted.");
            return;
        }

        const normalizedFile = await readFileAsBibFile(file);
        const normalizedText = await normalizedFile.text();
        this.ensureElements().inputTextArea.value = normalizedText;
        await this.submitText(normalizedText, normalizedFile.name);
    }

    async submitCurrentContent(): Promise<void> {
        const elements = this.ensureElements();
        await this.submitText(elements.inputTextArea.value, DEFAULT_INPUT_FILENAME);
    }

    downloadCurrentOutput(): void {
        const elements = this.ensureElements();
        const output = elements.outputTextArea.value.trim();

        if (!output) {
            this.showError("There is no cleaned bibliography to download yet.");
            return;
        }

        const blob = createDownloadBlob(output);
        const url = URL.createObjectURL(blob);
        const anchor = this.document.createElement("a");
        anchor.href = url;
        anchor.download = this.currentDownloadFilename;
        anchor.rel = "noopener";
        anchor.click();

        window.setTimeout(() => {
            URL.revokeObjectURL(url);
        }, 0);
    }

    setOutput(text: string, filename?: string | null): void {
        const elements = this.ensureElements();
        elements.outputTextArea.value = normalizeBibText(text);
        this.currentDownloadFilename = filename ?? DEFAULT_DOWNLOAD_FILENAME;
    }

    private async submitText(text: string, sourceFilename: string): Promise<void> {
        const normalizedText = normalizeBibText(text);
        if (!normalizedText.trim()) {
            this.showError("Paste or upload a .bib file before cleaning.");
            return;
        }

        const elements = this.ensureElements();
        const bibFile = createBibUploadFile(normalizedText, sourceFilename);
        const formData = new FormData();
        const options = [
            { name: "protect_caps", element: document.getElementById("protect_caps") as HTMLInputElement },
            { name: "dedup", element: document.getElementById("dedup") as HTMLInputElement },
            { name: "normalize_keys", element: document.getElementById("normalize_keys") as HTMLInputElement },
        ];
        options.forEach(option => {
            formData.append(option.name, option.element.checked ? "true" : "false");
        });
        formData.append("file", bibFile);

        this.setBusy(true, "Submitting bibliography for cleaning...");
        this.clearStatus();
        this.renderValidationResults([]);

        try {
            // 1. Submit the upload as a background job.
            const createResponse = await this.fetchImpl(`${this.apiBase}/jobs`, {
                method: "POST",
                body: formData,
            });
            if (!createResponse.ok) {
                throw new Error(await responseErrorMessage(createResponse));
            }
            const created = (await createResponse.json()) as { job_id?: string };
            if (!created.job_id) {
                throw new Error("Unexpected response from server (no job id).");
            }

            // 2. Poll until the job finishes.
            const final = await this.pollJob(created.job_id);
            if (final.status === "error") {
                throw new Error(final.error || "Processing failed.");
            }

            // 3. Download the cleaned result.
            const resultResponse = await this.fetchImpl(
                `${this.apiBase}/jobs/${created.job_id}/result`,
            );
            if (!resultResponse.ok) {
                throw new Error(await responseErrorMessage(resultResponse));
            }
            const cleaned = normalizeBibText(await resultResponse.text());
            const responseFilename = parseFilenameFromContentDisposition(
                resultResponse.headers.get("content-disposition"),
            );

            elements.outputTextArea.value = cleaned;
            this.currentDownloadFilename =
                responseFilename ?? deriveDownloadFilename(sourceFilename);

            this.setProcessingMessage("Validating output...");
            let will_validate = document.getElementById("validate") as HTMLInputElement;
            if (will_validate.checked) {
                const validationResults = await this.fetchValidationResults(
                    cleaned,
                    this.currentDownloadFilename,
                );
                this.renderValidationResults(validationResults);
                this.showSuccess("Bibliography cleaned and validated successfully.");
            } else {
                this.showSuccess("Bibliography cleaned successfully.");
            }
        } catch (error) {
            const message = error instanceof Error ? error.message : "Unexpected API error";
            this.showError(message);
        } finally {
            this.setBusy(false);
        }
    }

    private async fetchValidationResults(
        text: string,
        sourceFilename: string,
    ): Promise<ValidationResult[]> {
        const validationFile = createBibUploadFile(text, sourceFilename);
        const formData = new FormData();
        formData.append("file", validationFile);

        const response = await this.fetchImpl(this.validationEndpoint, {
            method: "POST",
            body: formData,
        });

        if (!response.ok) {
            throw new Error(await responseErrorMessage(response));
        }

        const payload = (await response.json()) as unknown;
        if (!Array.isArray(payload)) {
            throw new Error("Validation API returned an invalid payload.");
        }

        return payload as ValidationResult[];
    }

    private async pollJob(jobId: string): Promise<JobStatus> {
        let lastProgress = this.createProgressSnapshot({ status: "queued" });
        let lastActivityAt = Date.now();

        for (; ;) {
            const response = await this.fetchImpl(`${this.apiBase}/jobs/${jobId}`);
            if (!response.ok) {
                throw new Error(await responseErrorMessage(response));
            }

            const status = (await response.json()) as JobStatus;
            if (status.status === "done" || status.status === "error") {
                return status;
            }

            this.showProgress(status);

            const currentProgress = this.createProgressSnapshot(status);
            if (this.hasProgressChanged(lastProgress, currentProgress)) {
                lastProgress = currentProgress;
                lastActivityAt = Date.now();
            }

            if (Date.now() - lastActivityAt >= this.pollTimeoutMs) {
                throw new Error(
                    "Timed out waiting for job progress. The server appears stalled.",
                );
            }

            await this.delay(this.pollIntervalMs);
        }
    }

    private createProgressSnapshot(status: JobStatus): JobProgressSnapshot {
        return {
            status: status.status,
            done: typeof status.done === "number" ? status.done : null,
            total: typeof status.total === "number" ? status.total : null,
        };
    }

    private hasProgressChanged(
        previous: JobProgressSnapshot,
        next: JobProgressSnapshot,
    ): boolean {
        if (previous.status !== next.status) {
            return true;
        }

        if (previous.done !== next.done) {
            return true;
        }

        return previous.total !== next.total;
    }

    private delay(ms: number): Promise<void> {
        return new Promise((resolve) => setTimeout(resolve, ms));
    }

    private showProgress(status: JobStatus): void {
        const elements = this.ensureElements();
        this.setBusy(true, status.total
            ? `Cleaning… (${status.done ?? 0}/${status.total})`
            : "Cleaning…");
        // const label = status.total
        //     ? `Cleaning… (${status.done ?? 0}/${status.total})`
        //     : "Cleaning…";
        elements.status.dataset.state = "pending";
        // elements.status.textContent = label;
    }

    private setBusy(isBusy: boolean, message?: string): void {
        const elements = this.ensureElements();
        elements.uploadButton.disabled = isBusy;
        elements.cleanButton.disabled = isBusy;
        elements.downloadButton.disabled = isBusy;
        if (message) {
            elements.processingIndicatorText.textContent = message;
        }
        elements.processingIndicator.hidden = !isBusy;
    }

    private setProcessingMessage(message: string): void {
        const elements = this.ensureElements();
        elements.processingIndicatorText.textContent = message;
    }

    private renderValidationResults(results: ValidationResult[]): void {
        const elements = this.ensureElements();
        elements.validationContent.replaceChildren();

        if (!results.length) {
            elements.validationContainer.hidden = true;
            return;
        }

        const totalErrors = results.reduce((count, item) => count + item.errors.length, 0);
        const totalWarnings = results.reduce((count, item) => count + item.warnings.length, 0);
        elements.validationSummary.textContent =
            `Validation results (${results.length} entries, ${totalErrors} errors, ${totalWarnings} warnings)`;

        const fragment = this.document.createDocumentFragment();
        for (const result of results) {
            fragment.append(this.renderValidationEntry(result));
        }

        elements.validationContent.replaceChildren(fragment);
        elements.validationContainer.hidden = false;
        elements.validationDropdown.open = true;
    }

    private renderValidationEntry(result: ValidationResult): HTMLElement {
        const wrapper = this.document.createElement("article");
        wrapper.className = "validation-entry";

        const title = this.document.createElement("h3");
        title.className = "validation-entry__title";
        title.textContent = result.entry_id;
        wrapper.append(title);

        const errorsLine = this.document.createElement("p");
        errorsLine.className = "validation-entry__line validation-entry__line--error";
        if (result.errors.length > 0) {
            errorsLine.textContent = `Missing required: ${result.errors.join(", ")}`;
        }
        else { errorsLine.style.display = "none"; }
        wrapper.append(errorsLine);

        const warningsLine = this.document.createElement("p");
        warningsLine.className = "validation-entry__line validation-entry__line--warning";
        warningsLine.textContent =
            result.warnings.length > 0
                ? `Missing optional: ${result.warnings.join(", ")}`
                : "Missing optional: none";
        wrapper.append(warningsLine);

        return wrapper;
    }

    private showError(message: string): void {
        const elements = this.ensureElements();
        elements.status.dataset.state = "error";
        elements.status.textContent = message;
    }

    private showSuccess(message: string): void {
        const elements = this.ensureElements();
        elements.status.dataset.state = "success";
        elements.status.textContent = message;
    }

    private clearStatus(): void {
        const elements = this.ensureElements();
        elements.status.dataset.state = "";
        elements.status.textContent = "";
    }

    private ensureElements(): AppElements {
        if (!this.elements) {
            throw new Error("BibCleaner app is not mounted yet.");
        }

        return this.elements;
    }

    private queryElements(root: HTMLElement): AppElements {
        const query = <T extends Element>(selector: string) => {
            const element = root.querySelector<T>(selector);
            if (!element) {
                throw new Error(`Missing required element: ${selector}`);
            }

            return element;
        };

        return {
            root,
            status: query<HTMLParagraphElement>(".status-message"),
            inputTextArea: query<HTMLTextAreaElement>("[data-role='input-textarea']"),
            outputTextArea: query<HTMLTextAreaElement>("[data-role='output-textarea']"),
            uploadButton: query<HTMLButtonElement>("[data-action='upload']"),
            fileInput: query<HTMLInputElement>("[data-role='file-input']"),
            cleanButton: query<HTMLButtonElement>("[data-action='clean']"),
            processingIndicator: query<HTMLSpanElement>("[data-role='processing-indicator']"),
            processingIndicatorText: query<HTMLSpanElement>(".processing-indicator__text"),
            downloadButton: query<HTMLButtonElement>("[data-action='download']"),
            validationContainer: query<HTMLElement>("[data-role='validation-results']"),
            validationDropdown: query<HTMLDetailsElement>("[data-role='validation-dropdown']"),
            validationSummary: query<HTMLElement>("[data-role='validation-summary']"),
            validationContent: query<HTMLElement>("[data-role='validation-content']"),
        };
    }
}

export function bootstrapBibCleanerApp(options: BibCleanerAppOptions = {}): BibCleanerApp {
    const app = new BibCleanerApp(options);
    const container = (options.document ?? document).getElementById("app");

    if (!container) {
        throw new Error("Missing #app container element.");
    }

    app.mount(container);
    return app;
}