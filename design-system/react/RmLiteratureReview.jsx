import React from 'react';

export const RmLiteratureReview = ({ size = 24, color = 'currentColor', ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
  <circle cx="11" cy="11" r="7" />
  <line x1="16" y1="16" x2="21" y2="21" />
  <polyline points="8 10 9.5 11.5 13.5 7.5" strokeWidth="1.5" />
  <line x1="8" y1="14" x2="14" y2="14" strokeWidth="1.5" />
</svg>
);
