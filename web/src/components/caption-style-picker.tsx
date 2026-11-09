"use client";

import { CAPTION_OPTIONS } from "@/lib/render-options";
import type { CaptionStyle } from "@/lib/types";

export function CaptionStylePicker({
  value,
  disabled,
  onChange,
}: {
  value: CaptionStyle;
  disabled?: boolean;
  onChange: (value: CaptionStyle) => void;
}) {
  return (
    <div className="caption-style-grid" role="radiogroup" aria-label="Caption style">
      {CAPTION_OPTIONS.map((option) => (
        <button
          aria-checked={value === option.value}
          className={value === option.value ? "selected" : ""}
          disabled={disabled}
          key={option.value}
          role="radio"
          title={option.description}
          type="button"
          onClick={() => onChange(option.value)}
        >
          <span className={`caption-sample sample-${option.value}`}>
            <span>Make</span> <span className="active">it</span> <span>count</span>
          </span>
          <small>{option.label}</small>
        </button>
      ))}
    </div>
  );
}
