import React from 'react';

export const RmAiAssistant = ({ size = 24, color = 'currentColor', ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
  <circle cx="11" cy="11" r="7" />
  <line x1="16" y1="16" x2="21" y2="21" />
  <path d="M8 9h6a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-3l-2 2v-2H8a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1z" strokeWidth="1.2" />
  <circle cx="10" cy="11.5" r="0.8" fill={color} stroke="none" />
  <circle cx="12" cy="11.5" r="0.8" fill={color} stroke="none" />
</svg>
);
