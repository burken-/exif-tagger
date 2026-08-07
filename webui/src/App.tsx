import { useState, useEffect } from 'react';
import { ThemeProvider } from '@/context/ThemeContext';
import { Header } from '@/components/layout/Header';
import { Navigation, TabType } from '@/components/layout/Navigation';
import { ToastProvider } from '@/components/layout/ToastContainer';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Play, Image, Settings, Calendar } from 'lucide-react';

export function AppContent() {
  const [activeTab, setActiveTab] = useState<TabType>(() => {
    const hash = window.location.hash.toLowerCase();
    if (hash.includes('gallery')) return 'gallery';
    if (hash.includes('config')) return 'config';
    if (hash.includes('schedule')) return 'schedule';
    return 'processing';
  });

  useEffect(() => {
    const handleHashChange = () => {
      const hash = window.location.hash.toLowerCase();
      if (hash.includes('gallery')) setActiveTab('gallery');
      else if (hash.includes('config')) setActiveTab('config');
      else if (hash.includes('schedule')) setActiveTab('schedule');
      else if (hash.includes('processing')) setActiveTab('processing');
    };

    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, []);

  const handleTabChange = (tab: TabType) => {
    setActiveTab(tab);
    if (!window.location.hash.startsWith(`#${tab}`)) {
      window.location.hash = `#${tab}`;
    }
  };

  const renderTabContent = () => {
    switch (activeTab) {
      case 'processing':
        return (
          <div className="space-y-6">
            <Card className="border-border">
              <CardHeader>
                <div className="flex items-center gap-2">
                  <Play className="w-5 h-5 text-primary" />
                  <CardTitle>Processing Dashboard</CardTitle>
                </div>
                <CardDescription>
                  Start image processing sessions, monitor progress, and view live logs.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">
                  Processing Tab components will be rendered here.
                </p>
              </CardContent>
            </Card>
          </div>
        );
      case 'gallery':
        return (
          <div className="space-y-6">
            <Card className="border-border">
              <CardHeader>
                <div className="flex items-center gap-2">
                  <Image className="w-5 h-5 text-primary" />
                  <CardTitle>Image Gallery</CardTitle>
                </div>
                <CardDescription>
                  Browse images, filter by tags, and manage EXIF tags.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">
                  Gallery Tab components will be rendered here.
                </p>
              </CardContent>
            </Card>
          </div>
        );
      case 'config':
        return (
          <div className="space-y-6">
            <Card className="border-border">
              <CardHeader>
                <div className="flex items-center gap-2">
                  <Settings className="w-5 h-5 text-primary" />
                  <CardTitle>Configuration Settings</CardTitle>
                </div>
                <CardDescription>
                  Configure system parameters, LLM backend settings, and tag prompts.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">
                  Configuration Tab components will be rendered here.
                </p>
              </CardContent>
            </Card>
          </div>
        );
      case 'schedule':
        return (
          <div className="space-y-6">
            <Card className="border-border">
              <CardHeader>
                <div className="flex items-center gap-2">
                  <Calendar className="w-5 h-5 text-primary" />
                  <CardTitle>Scheduled Tasks</CardTitle>
                </div>
                <CardDescription>
                  View and manage cron-scheduled tagging jobs.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">
                  Schedule Tab components will be rendered here.
                </p>
              </CardContent>
            </Card>
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col font-sans antialiased">
      <Header />
      <Navigation activeTab={activeTab} onTabChange={handleTabChange} />
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {renderTabContent()}
      </main>
    </div>
  );
}

export function App() {
  return (
    <ThemeProvider defaultTheme="dark" storageKey="exif-tagger-theme">
      <ToastProvider>
        <AppContent />
      </ToastProvider>
    </ThemeProvider>
  );
}

export default App;
