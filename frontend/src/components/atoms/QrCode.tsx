import { useEffect, useState } from "react";
import QRCode from "qrcode";

/**
 * A QR code rendered client-side as SVG (S8).
 *
 * Deliberate choices, because a QR that will not scan is worse than none:
 *
 * - **SVG**, so it stays sharp at any size and needs no canvas.
 * - a **4-module quiet zone** (`margin: 4`) — scanners need their breathing room;
 * - **black on white, never inverted**: light-on-dark codes fail on older phone
 *   cameras, so the colours are fixed here and the card behind it is white;
 * - the payload is an `https://t.me/...` link, never a `tg://` scheme, which
 *   native camera apps do not open.
 */
export function QrCode({
  value,
  label,
  size = 192,
}: {
  value: string;
  label: string;
  size?: number;
}) {
  const [svg, setSvg] = useState("");

  useEffect(() => {
    let active = true;
    setSvg("");
    void QRCode.toString(value, {
      type: "svg",
      margin: 4,
      errorCorrectionLevel: "M",
      color: { dark: "#000000", light: "#ffffff" },
    })
      .then((next) => {
        if (active) setSvg(next);
      })
      .catch(() => {
        // A QR that cannot be drawn simply does not render; the link and the
        // code below stay usable.
        if (active) setSvg("");
      });
    return () => {
      active = false;
    };
  }, [value]);

  return (
    <div
      role="img"
      aria-label={label}
      data-testid="bugreport-qr"
      className="rounded-lg bg-white p-2"
      style={{ width: size }}
    >
      {svg ? (
        <span
          className="block [&>svg]:h-auto [&>svg]:w-full"
          data-testid="bugreport-qr-svg"
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      ) : null}
    </div>
  );
}
