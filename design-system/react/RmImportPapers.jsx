import React from 'react';

export const RmImportPapers = ({ size = 24, color = 'currentColor', ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
  <circle cx="11" cy="11" r="7" />
  <line x1="16" y1="16" x2="21" y2="21" />
  <path d="M11 7v7M8 11l3 3 3-3" strokeWidth="1.5" />
</svg>
);
