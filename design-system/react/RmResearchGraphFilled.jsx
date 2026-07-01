import React from 'react';

export const RmResearchGraphFilled = ({ size = 24, color = 'currentColor', ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={color}>
  <path d="M11 2a9 9 0 0 1 6.36 15.36L21 21a1 1 0 0 1-1.41 1.41l-3.64-3.64A9 9 0 1 1 11 2zm0 2a7 7 0 1 0 0 14 7 7 0 0 0 0-14z" />
  <circle cx="11" cy="9" r="1.5" />
  <circle cx="8" cy="13" r="1.5" />
  <circle cx="14" cy="13" r="1.5" />
  <line x1="11" y1="9" x2="8" y2="13" stroke={color} strokeWidth="1.5" />
  <line x1="11" y1="9" x2="14" y2="13" stroke={color} strokeWidth="1.5" />
</svg>
);
