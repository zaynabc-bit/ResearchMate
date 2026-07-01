import React from 'react';

export const RmAiCompare = ({ size = 24, color = 'currentColor', ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
  <circle cx="11" cy="11" r="7" />
  <line x1="16" y1="16" x2="21" y2="21" />
  <rect x="7.5" y="8" width="3" height="6" rx="0.5" strokeWidth="1.2" />
  <rect x="11.5" y="8" width="3" height="6" rx="0.5" strokeWidth="1.2" />
</svg>
);
