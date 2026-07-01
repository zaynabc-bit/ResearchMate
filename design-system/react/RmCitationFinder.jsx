import React from 'react';

export const RmCitationFinder = ({ size = 24, color = 'currentColor', ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
  <circle cx="11" cy="11" r="7" />
  <line x1="16" y1="16" x2="21" y2="21" />
  <path d="M8 12a2 2 0 0 1 2-2V8a4 4 0 0 0-4 4h2zm5 0a2 2 0 0 1 2-2V8a4 4 0 0 0-4 4h2z" fill={color} stroke="none" />
</svg>
);
