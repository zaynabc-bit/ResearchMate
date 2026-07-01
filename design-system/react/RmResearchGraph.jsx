import React from 'react';

export const RmResearchGraph = ({ size = 24, color = 'currentColor', ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
  <circle cx="11" cy="11" r="7" />
  <line x1="16" y1="16" x2="21" y2="21" />
  <circle cx="11" cy="9" r="1" fill={color} stroke="none" />
  <circle cx="8" cy="13" r="1" fill={color} stroke="none" />
  <circle cx="14" cy="13" r="1" fill={color} stroke="none" />
  <line x1="11" y1="9" x2="8" y2="13" strokeWidth="1" />
  <line x1="11" y1="9" x2="14" y2="13" strokeWidth="1" />
  <line x1="8" y1="13" x2="14" y2="13" strokeWidth="1" />
</svg>
);
