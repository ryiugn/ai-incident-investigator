import { defineConfig } from '@playwright/test';
export default defineConfig({testDir:'tests', use:{headless:true,channel:'chrome'}, timeout:30000, reporter:'list'});
