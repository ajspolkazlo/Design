import { ImageResponse } from "next/og";

export const size = { width: 32, height: 32 };
export const contentType = "image/png";

export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#FF4C91",
          borderRadius: 8,
          color: "#FFFFFF",
          fontSize: 16,
          fontWeight: 700,
          fontFamily: "monospace",
        }}
      >
        bs
      </div>
    ),
    { ...size }
  );
}
