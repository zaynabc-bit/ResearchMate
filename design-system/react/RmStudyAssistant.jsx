import React from 'react';

export const RmStudyAssistant = ({ size = 24, color = 'currentColor', ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
  <circle cx="11" cy="11" r="7" />
  <line x1="16" y1="16" x2="21" y2="21" />
  <path d="M11 7.5l4.5 2.25L11 12 6.5 9.75z" strokeWidth="1.2" />
  <path d="M8 10.5v2.5c0 1 1.34 1.5 3 1.5s3-.5 3-1.5v-2.5" strokeWidth="1.2" />
</svg>
);
