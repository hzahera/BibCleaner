// Polyfills for APIs this jsdom build doesn't implement, so tests can exercise
// the same code paths the browser runs.

if (typeof Blob !== "undefined" && typeof Blob.prototype.text !== "function") {
    Blob.prototype.text = function text(this: Blob): Promise<string> {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result ?? ""));
            reader.onerror = () => reject(reader.error);
            reader.readAsText(this);
        });
    };
}

const urlCtor = URL as unknown as {
    createObjectURL?: (obj: unknown) => string;
    revokeObjectURL?: (url: string) => void;
};
if (typeof urlCtor.createObjectURL !== "function") {
    urlCtor.createObjectURL = () => "blob:mock";
}
if (typeof urlCtor.revokeObjectURL !== "function") {
    urlCtor.revokeObjectURL = () => undefined;
}
