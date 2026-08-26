import { describe, expect, it } from "vitest";
import {
  initialUploadState,
  uploadReducer,
  validateUpload,
  type UploadState,
} from "./uploadMachine";

const PDF = new File(["%PDF-1.4"], "scan.pdf", { type: "application/pdf" });

function uploading(overrides?: Partial<Extract<UploadState, { status: "uploading" }>>): UploadState {
  return {
    status: "uploading",
    file: PDF,
    progress: 0,
    attempt: 1,
    ...overrides,
  };
}

describe("validateUpload", () => {
  it("accepts pdf/jpeg/png/tiff", () => {
    expect(validateUpload(PDF)).toBeNull();
    expect(
      validateUpload(new File(["x"], "a.jpg", { type: "image/jpeg" })),
    ).toBeNull();
    expect(
      validateUpload(new File(["x"], "a.png", { type: "image/png" })),
    ).toBeNull();
    expect(
      validateUpload(new File(["x"], "a.tif", { type: "image/tiff" })),
    ).toBeNull();
  });

  it("rejects unsupported types", () => {
    const message = validateUpload(new File(["x"], "a.txt", { type: "text/plain" }));
    expect(message).toMatch(/Поддерживаются/);
  });

  it("rejects files over 50 MB", () => {
    const big = new File([new ArrayBuffer(51 * 1024 * 1024)], "big.pdf", {
      type: "application/pdf",
    });
    expect(validateUpload(big)).toMatch(/50 МБ/);
  });

  it("rejects empty files", () => {
    const empty = new File([], "empty.pdf", { type: "application/pdf" });
    expect(validateUpload(empty)).toMatch(/пустой/);
  });
});

describe("uploadReducer transitions", () => {
  it("idle → validating on SELECT", () => {
    const next = uploadReducer(initialUploadState, { type: "SELECT", file: PDF });
    expect(next).toEqual({ status: "validating", file: PDF });
  });

  it("validating → error on VALIDATION_FAILED", () => {
    const next = uploadReducer({ status: "validating", file: PDF }, {
      type: "VALIDATION_FAILED",
      message: "bad",
    });
    expect(next).toEqual({ status: "error", message: "bad", file: null, attempt: 0 });
  });

  it("validating → uploading on UPLOAD_START with progress reset", () => {
    const next = uploadReducer({ status: "validating", file: PDF }, {
      type: "UPLOAD_START",
      attempt: 1,
    });
    expect(next).toEqual({ status: "uploading", file: PDF, progress: 0, attempt: 1 });
  });

  it("PROGRESS never decreases and clamps at 100", () => {
    let state = uploading({ progress: 40 });
    state = uploadReducer(state, { type: "PROGRESS", percent: 20 });
    expect(state).toMatchObject({ progress: 40 });
    state = uploadReducer(state, { type: "PROGRESS", percent: 120 });
    expect(state).toMatchObject({ progress: 100 });
  });

  it("uploading → queued on UPLOADED and remembers the file name", () => {
    const next = uploadReducer(uploading(), {
      type: "UPLOADED",
      documentId: "doc-1",
    });
    expect(next).toEqual({ status: "queued", documentId: "doc-1", fileName: "scan.pdf" });
  });

  it("uploading → error on ERROR keeping file and attempt", () => {
    const next = uploadReducer(uploading({ progress: 55 }), {
      type: "ERROR",
      message: "boom",
    });
    expect(next).toEqual({ status: "error", message: "boom", file: PDF, attempt: 1 });
  });

  it("error → retry increments attempt and resets progress", () => {
    const errored = uploadReducer(uploading({ progress: 55 }), {
      type: "ERROR",
      message: "boom",
    });
    const next = uploadReducer(errored, { type: "RETRY" });
    expect(next).toEqual({ status: "uploading", file: PDF, progress: 0, attempt: 2 });
  });

  it("RETRY outside error state is a no-op", () => {
    expect(uploadReducer(initialUploadState, { type: "RETRY" })).toBe(
      initialUploadState,
    );
  });

  it("uploading → cancelled on CANCEL; queued survives CANCEL", () => {
    expect(uploadReducer(uploading(), { type: "CANCEL" })).toEqual({
      status: "cancelled",
    });
    const queued = uploadReducer(uploading(), { type: "UPLOADED", documentId: "d" });
    expect(uploadReducer(queued, { type: "CANCEL" })).toEqual(queued);
  });

  it("FAILED_STATUS captures terminal backend failure with document id", () => {
    const next = uploadReducer(uploading(), {
      type: "FAILED_STATUS",
      documentId: "doc-9",
    });
    expect(next).toEqual({ status: "failed", documentId: "doc-9" });
  });

  it("RESET returns to idle from any state", () => {
    expect(uploadReducer({ status: "cancelled" }, { type: "RESET" })).toBe(
      initialUploadState,
    );
  });

  it("ignores PROGRESS outside uploading", () => {
    expect(
      uploadReducer(initialUploadState, { type: "PROGRESS", percent: 10 }),
    ).toBe(initialUploadState);
  });
});
