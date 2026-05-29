import {
    API_ENDPOINT,
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

type FetchLike = typeof fetch;

interface AppElements {
    root: HTMLElement;
    status: HTMLParagraphElement;
    inputTextArea: HTMLTextAreaElement;
    outputTextArea: HTMLTextAreaElement;
    uploadButton: HTMLButtonElement;
    fileInput: HTMLInputElement;
    cleanButton: HTMLButtonElement;
    processingIndicator: HTMLSpanElement;
    downloadButton: HTMLButtonElement;
}

export interface BibCleanerAppOptions {
    document?: Document;
    fetchImpl?: FetchLike;
    apiEndpoint?: string;
}

export class BibCleanerApp {
    private readonly document: Document;
    private readonly fetchImpl: FetchLike;
    private readonly apiEndpoint: string;
    private elements: AppElements | null = null;
    private currentDownloadFilename = DEFAULT_DOWNLOAD_FILENAME;

    constructor(options: BibCleanerAppOptions = {}) {
        this.document = options.document ?? document;
        this.fetchImpl = options.fetchImpl ?? fetch.bind(globalThis);
        this.apiEndpoint = options.apiEndpoint ?? API_ENDPOINT;
    }

    mount(container: HTMLElement): HTMLElement {
        const root = this.document.createElement("div");
        root.className = "app-shell";
        root.innerHTML = `
      <header class="app-header">
        <h1>BibCleaner</h1>
      </header>
      <p class="status-message" role="alert" aria-live="polite"></p>
      <main class="app-main">
        <section class="panel panel--input" aria-label="Input bibliography">
          <div class="panel__toolbar">
            <label for="bib-input">Please, write or upload you .bib file</label>
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
        </section>
      </main>
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
        formData.append("file", bibFile);

        this.setBusy(true);
        this.clearStatus();

        try {
            const response = await this.fetchImpl(this.apiEndpoint, {
                method: "POST",
                body: formData,
            });

            if (!response.ok) {
                throw new Error(await responseErrorMessage(response));
            }

            const cleaned = normalizeBibText(await response.text());
            const responseFilename = parseFilenameFromContentDisposition(
                response.headers.get("content-disposition"),
            );

            elements.outputTextArea.value = cleaned;
            this.currentDownloadFilename =
                responseFilename ?? deriveDownloadFilename(sourceFilename);
            this.showSuccess("Bibliography cleaned successfully.");
        } catch (error) {
            const message = error instanceof Error ? error.message : "Unexpected API error";
            this.showError(message);
        } finally {
            this.setBusy(false);
        }
    }

    private setBusy(isBusy: boolean): void {
        const elements = this.ensureElements();
        elements.uploadButton.disabled = isBusy;
        elements.cleanButton.disabled = isBusy;
        elements.downloadButton.disabled = isBusy;
        elements.processingIndicator.hidden = !isBusy;
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
            downloadButton: query<HTMLButtonElement>("[data-action='download']"),
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