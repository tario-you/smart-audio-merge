#import <AppKit/AppKit.h>
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>
#import <QuartzCore/QuartzCore.h>
#import "Engine.h"

static NSString *MergeDuration(double value) {
    NSInteger s = MAX(0, lround(value));
    return s >= 3600 ? [NSString stringWithFormat:@"%ld:%02ld:%02ld", s/3600, s/60%60, s%60]
                     : [NSString stringWithFormat:@"%ld:%02ld", s/60, s%60];
}

@interface MergeBackground : NSView
@end
@implementation MergeBackground
- (BOOL)isOpaque { return YES; }
- (void)drawRect:(NSRect)dirtyRect {
    [[NSColor colorWithWhite:0.94 alpha:1] setFill]; NSRectFill(dirtyRect);
}
@end

@interface MergeApp : NSObject <NSApplicationDelegate, NSWindowDelegate, NSTableViewDataSource, NSTableViewDelegate>
@property NSWindow *window;
@property NSTableView *table;
@property NSTextField *subtitle;
@property NSTextField *status;
@property NSProgressIndicator *progress;
@property NSPopUpButton *format;
@property NSButton *mergeButton;
@property NSButton *cancelButton;
@property NSButton *upButton;
@property NSButton *downButton;
@property MergeEngine *engine;
@property NSMutableArray<NSDictionary *> *items;
@property BOOL busy;
@property NSURL *output;
@property NSURL *qaDirectory;
@property NSString *lastError;
@end

@implementation MergeApp
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    NSString *qa = NSProcessInfo.processInfo.environment[@"SMART_AUDIO_MERGE_QA_DIR"];
    if (qa) self.qaDirectory = [NSURL fileURLWithPath:qa];
    self.engine = [MergeEngine new];
    self.items = [NSMutableArray array];
    self.lastError = @"The audio operation failed.";
    [self buildUI];
    NSArray *args = NSProcessInfo.processInfo.arguments;
    NSUInteger first = args.count > 1 && [args[1] hasPrefix:@"--qa-dir="] ? 2 : 1;
    if (args.count > first) [self load:[args subarrayWithRange:NSMakeRange(first, args.count - first)]];
    else {
        [self setWorking:NO];
        self.subtitle.stringValue = @"Select audio files in Finder, then choose Quick Actions > Smart Audio Merge.";
    }
}
- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender { return YES; }
- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender {
    if (self.busy) { [self closeOrCancel:nil]; return NSTerminateCancel; }
    return NSTerminateNow;
}
- (NSButton *)button:(NSString *)title action:(SEL)action {
    return [NSButton buttonWithTitle:title target:self action:action];
}
- (void)buildUI {
    self.window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 780, 590)
        styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable
        backing:NSBackingStoreBuffered defer:NO];
    self.window.title = @"Smart Audio Merge";
    self.window.appearance = [NSAppearance appearanceNamed:NSAppearanceNameAqua];
    self.window.minSize = NSMakeSize(670, 510);
    self.window.releasedWhenClosed = NO;
    self.window.delegate = self;
    self.window.contentView = [[MergeBackground alloc] initWithFrame:self.window.contentView.bounds];
    NSView *root = self.window.contentView;
    NSTextField *title = [NSTextField labelWithString:@"Merge audio files"];
    title.font = [NSFont systemFontOfSize:24 weight:NSFontWeightSemibold];
    self.subtitle = [NSTextField wrappingLabelWithString:@"Reading selected audio files…"];
    self.subtitle.font = [NSFont systemFontOfSize:13];
    self.subtitle.textColor = NSColor.secondaryLabelColor;
    NSScrollView *scroll = [NSScrollView new];
    scroll.hasVerticalScroller = YES;
    scroll.borderType = NSBezelBorder;
    self.table = [NSTableView new];
    self.table.usesAlternatingRowBackgroundColors = YES;
    self.table.rowHeight = 30;
    self.table.allowsMultipleSelection = YES;
    self.table.columnAutoresizingStyle = NSTableViewUniformColumnAutoresizingStyle;
    for (NSArray *spec in @[@[@"order", @"Order", @52], @[@"name", @"File", @540], @[@"duration", @"Duration", @110]]) {
        NSTableColumn *column = [[NSTableColumn alloc] initWithIdentifier:spec[0]];
        column.title = spec[1]; column.width = [spec[2] doubleValue];
        column.minWidth = [spec[0] isEqual:@"name"] ? 220 : column.width;
        column.resizingMask = [spec[0] isEqual:@"name"] ? NSTableColumnAutoresizingMask : NSTableColumnNoResizing;
        [self.table addTableColumn:column];
    }
    self.table.dataSource = self; self.table.delegate = self;
    scroll.documentView = self.table;
    self.upButton = [self button:@"Move Up" action:@selector(moveUp:)];
    self.downButton = [self button:@"Move Down" action:@selector(moveDown:)];
    NSTextField *hint = [NSTextField labelWithString:@"Review the order. Select rows to move them."];
    hint.textColor = NSColor.secondaryLabelColor; hint.font = [NSFont systemFontOfSize:12];
    NSStackView *reorder = [NSStackView stackViewWithViews:@[self.upButton, self.downButton, hint]];
    reorder.spacing = 10;
    self.format = [NSPopUpButton new];
    [self.format addItemsWithTitles:@[@"MP3 · High quality", @"M4A · High quality", @"FLAC · Lossless", @"WAV · Lossless"]];
    NSTextField *safety = [NSTextField labelWithString:@"Source files stay unchanged."];
    safety.font = [NSFont systemFontOfSize:12]; safety.textColor = NSColor.secondaryLabelColor;
    NSStackView *options = [NSStackView stackViewWithViews:@[[NSTextField labelWithString:@"Save as:"], self.format, safety]];
    options.spacing = 10;
    self.status = [NSTextField wrappingLabelWithString:@""];
    self.status.font = [NSFont systemFontOfSize:12]; self.status.maximumNumberOfLines = 2;
    self.progress = [NSProgressIndicator new];
    self.progress.indeterminate = NO; self.progress.minValue = 0; self.progress.maxValue = 1;
    self.progress.style = NSProgressIndicatorStyleBar;
    self.mergeButton = [self button:@"Merge…" action:@selector(saveAndMerge:)];
    self.mergeButton.keyEquivalent = @"\r";
    self.cancelButton = [self button:@"Close" action:@selector(closeOrCancel:)];
    self.cancelButton.keyEquivalent = @"\x1b";
    NSStackView *footer = [NSStackView stackViewWithViews:@[self.cancelButton, self.mergeButton]];
    footer.spacing = 10;
    for (NSView *view in @[title, self.subtitle, scroll, reorder, options, self.status, self.progress, footer]) {
        view.translatesAutoresizingMaskIntoConstraints = NO; [root addSubview:view];
    }
    [NSLayoutConstraint activateConstraints:@[
        [title.leadingAnchor constraintEqualToAnchor:root.leadingAnchor constant:24],
        [title.topAnchor constraintEqualToAnchor:root.topAnchor constant:22],
        [self.subtitle.leadingAnchor constraintEqualToAnchor:title.leadingAnchor],
        [self.subtitle.trailingAnchor constraintEqualToAnchor:root.trailingAnchor constant:-24],
        [self.subtitle.topAnchor constraintEqualToAnchor:title.bottomAnchor constant:8],
        [self.subtitle.heightAnchor constraintEqualToConstant:38],
        [scroll.topAnchor constraintEqualToAnchor:self.subtitle.bottomAnchor constant:14],
        [scroll.leadingAnchor constraintEqualToAnchor:title.leadingAnchor],
        [scroll.trailingAnchor constraintEqualToAnchor:self.subtitle.trailingAnchor],
        [scroll.bottomAnchor constraintEqualToAnchor:reorder.topAnchor constant:-10],
        [reorder.leadingAnchor constraintEqualToAnchor:title.leadingAnchor],
        [reorder.bottomAnchor constraintEqualToAnchor:options.topAnchor constant:-12],
        [options.leadingAnchor constraintEqualToAnchor:title.leadingAnchor],
        [options.bottomAnchor constraintEqualToAnchor:self.status.topAnchor constant:-13],
        [self.status.leadingAnchor constraintEqualToAnchor:title.leadingAnchor],
        [self.status.trailingAnchor constraintEqualToAnchor:self.subtitle.trailingAnchor],
        [self.status.heightAnchor constraintEqualToConstant:32],
        [self.status.bottomAnchor constraintEqualToAnchor:self.progress.topAnchor constant:-5],
        [self.progress.leadingAnchor constraintEqualToAnchor:title.leadingAnchor],
        [self.progress.trailingAnchor constraintEqualToAnchor:self.subtitle.trailingAnchor],
        [self.progress.bottomAnchor constraintEqualToAnchor:footer.topAnchor constant:-15],
        [footer.trailingAnchor constraintEqualToAnchor:self.subtitle.trailingAnchor],
        [footer.bottomAnchor constraintEqualToAnchor:root.bottomAnchor constant:-18]
    ]];
    [self setWorking:YES];
    if (!self.qaDirectory) {
        [self.window center]; [self.window makeKeyAndOrderFront:nil]; [NSApp activateIgnoringOtherApps:YES];
    }
}
- (void)load:(NSArray *)paths {
    [self.engine run:[@[@"plan", @"--"] arrayByAddingObjectsFromArray:paths] event:^(NSDictionary *value) {
        if (value[@"message"]) self.lastError = value[@"message"];
    } done:^(int code, NSData *data) {
        [self setWorking:NO];
        NSDictionary *plan = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
        if (code || !plan[@"items"]) { [self showError:self.lastError]; return; }
        self.items = [plan[@"items"] mutableCopy]; [self.table reloadData];
        double total = 0; for (NSDictionary *item in self.items) total += [item[@"duration"] doubleValue];
        self.subtitle.stringValue = [NSString stringWithFormat:@"%lu files · %@ total · %@\n%@", self.items.count, MergeDuration(total), plan[@"mode"], plan[@"detail"]];
        self.status.stringValue = [plan[@"warnings"] firstObject] ?: @"Ready to merge in the order shown.";
        self.mergeButton.enabled = YES; [self updateMoveButtons];
        if (self.qaDirectory) {
            [data writeToURL:[self.qaDirectory URLByAppendingPathComponent:@"plan.json"] atomically:YES];
            [self snapshot:@"preview.png"];
            NSArray *original = [self.items copy];
            [self.table selectRowIndexes:[NSIndexSet indexSetWithIndex:1] byExtendingSelection:NO];
            [self move:-1]; NSAssert([self.items[0] isEqual:original[1]], @"Move Up failed");
            [self move:1]; NSAssert([self.items isEqual:original], @"Move Down failed");
            [self.table deselectAll:nil];
            [self.window setContentSize:NSMakeSize(670, 488)]; [self snapshot:@"compact.png"];
            [self.window setContentSize:NSMakeSize(780, 590)];
            [self beginMerge:[self.qaDirectory URLByAppendingPathComponent:@"workflow-merged.mp3"]];
        }
    }];
}
- (NSInteger)numberOfRowsInTableView:(NSTableView *)tableView { return self.items.count; }
- (NSView *)tableView:(NSTableView *)tableView viewForTableColumn:(NSTableColumn *)column row:(NSInteger)row {
    NSDictionary *item = self.items[row];
    NSString *text = [column.identifier isEqual:@"order"] ? [NSString stringWithFormat:@"%ld", row+1] :
        [column.identifier isEqual:@"name"] ? item[@"name"] : MergeDuration([item[@"duration"] doubleValue]);
    NSTextField *cell = [NSTextField labelWithString:text];
    cell.font = [NSFont systemFontOfSize:13]; cell.lineBreakMode = NSLineBreakByTruncatingMiddle;
    cell.toolTip = item[@"path"]; return cell;
}
- (void)tableViewSelectionDidChange:(NSNotification *)notification { [self updateMoveButtons]; }
- (void)fitColumns {
    CGFloat available = self.table.enclosingScrollView.contentSize.width;
    if (available > 0) {
        self.table.tableColumns[1].width = MAX(220, available - 166);
        [self.table sizeToFit];
    }
}
- (void)windowDidResize:(NSNotification *)notification {
    [self.window.contentView layoutSubtreeIfNeeded]; [self fitColumns];
}
- (void)updateMoveButtons {
    NSIndexSet *rows = self.table.selectedRowIndexes;
    self.upButton.enabled = !self.busy && rows.count && rows.firstIndex > 0;
    self.downButton.enabled = !self.busy && rows.count && rows.lastIndex < self.items.count - 1;
}
- (void)moveUp:(id)sender { [self move:-1]; }
- (void)moveDown:(id)sender { [self move:1]; }
- (void)move:(NSInteger)delta {
    NSIndexSet *rows = self.table.selectedRowIndexes;
    if (self.busy || !rows.count || (delta < 0 && rows.firstIndex == 0) || (delta > 0 && rows.lastIndex >= self.items.count - 1)) return;
    NSMutableIndexSet *moved = [NSMutableIndexSet indexSet];
    [rows enumerateIndexesWithOptions:delta < 0 ? 0 : NSEnumerationReverse usingBlock:^(NSUInteger index, BOOL *stop) {
        [self.items exchangeObjectAtIndex:index withObjectAtIndex:(NSInteger)index + delta];
        [moved addIndex:(NSInteger)index + delta];
    }];
    [self.table reloadData]; [self.table selectRowIndexes:moved byExtendingSelection:NO];
    self.status.stringValue = @"Using your adjusted order.";
}
- (void)setWorking:(BOOL)value {
    self.busy = value; self.mergeButton.enabled = !value && self.items.count >= 2;
    self.format.enabled = !value; self.table.enabled = !value;
    self.cancelButton.title = value ? @"Cancel" : @"Close"; [self updateMoveButtons];
}
- (void)saveAndMerge:(id)sender {
    if (self.output) { [NSWorkspace.sharedWorkspace activateFileViewerSelectingURLs:@[self.output]]; return; }
    NSString *suffix = @[@"mp3", @"m4a", @"flac", @"wav"][self.format.indexOfSelectedItem];
    NSSavePanel *panel = [NSSavePanel savePanel];
    panel.title = @"Save merged audio"; panel.prompt = @"Merge";
    panel.allowedContentTypes = @[[UTType typeWithFilenameExtension:suffix] ?: UTTypeAudio];
    panel.canCreateDirectories = YES; panel.extensionHidden = NO;
    NSURL *folder = [[NSURL fileURLWithPath:self.items[0][@"path"]] URLByDeletingLastPathComponent];
    panel.directoryURL = folder;
    NSString *name = [@"Merged Audio." stringByAppendingString:suffix];
    NSInteger n = 2;
    while ([NSFileManager.defaultManager fileExistsAtPath:[folder URLByAppendingPathComponent:name].path])
        name = [NSString stringWithFormat:@"Merged Audio %ld.%@", n++, suffix];
    panel.nameFieldStringValue = name;
    [panel beginSheetModalForWindow:self.window completionHandler:^(NSModalResponse response) {
        if (response == NSModalResponseOK && panel.URL) [self beginMerge:panel.URL];
    }];
}
- (void)beginMerge:(NSURL *)destination {
    [self setWorking:YES]; self.progress.doubleValue = 0; self.status.stringValue = @"Preparing the merge…";
    NSArray *args = [@[@"merge", @"--keep-order", @"--output", destination.path, @"--"] arrayByAddingObjectsFromArray:[self.items valueForKey:@"path"]];
    [self.engine run:args event:^(NSDictionary *event) {
        if (event[@"message"]) { self.status.stringValue = event[@"message"]; self.lastError = event[@"message"]; }
        if (event[@"fraction"]) self.progress.doubleValue = [event[@"fraction"] doubleValue];
    } done:^(int code, NSData *data) {
        [self setWorking:NO];
        if (!code) {
            self.output = destination; self.progress.doubleValue = 1;
            self.status.stringValue = [NSString stringWithFormat:@"Saved %@. Your source files are unchanged.", destination.lastPathComponent];
            self.mergeButton.title = @"Show in Finder";
            self.format.enabled = NO; self.table.enabled = NO; self.upButton.enabled = NO; self.downButton.enabled = NO;
            if (self.qaDirectory) {
                [self snapshot:@"complete.png"];
                [@"complete\n" writeToURL:[self.qaDirectory URLByAppendingPathComponent:@"result.txt"] atomically:YES encoding:NSUTF8StringEncoding error:nil];
                [NSApp terminate:nil];
            }
        } else if (code == 130 || code == 15) self.status.stringValue = @"Merge cancelled. Your source files are unchanged.";
        else [self showError:self.lastError];
    }];
}
- (void)showError:(NSString *)message {
    self.status.stringValue = message;
    if (self.qaDirectory) {
        [self snapshot:@"error.png"];
        [message writeToURL:[self.qaDirectory URLByAppendingPathComponent:@"error.txt"] atomically:YES encoding:NSUTF8StringEncoding error:nil];
        [NSApp terminate:nil]; return;
    }
    NSAlert *alert = [NSAlert new]; alert.messageText = @"Audio merge needs attention"; alert.informativeText = message;
    [alert beginSheetModalForWindow:self.window completionHandler:nil];
}
- (void)closeOrCancel:(id)sender {
    if (self.busy) { self.status.stringValue = @"Cancelling…"; [self.engine cancel]; }
    else [self.window close];
}
- (BOOL)windowShouldClose:(NSWindow *)sender {
    if (self.busy) { [self closeOrCancel:nil]; return NO; } return YES;
}
- (void)snapshot:(NSString *)name {
    NSView *view = self.window.contentView;
    [self.window.appearance ?: self.window.effectiveAppearance performAsCurrentDrawingAppearance:^{
        [view layoutSubtreeIfNeeded]; [self fitColumns]; [view displayIfNeeded]; [CATransaction flush];
        NSBitmapImageRep *bitmap = [view bitmapImageRepForCachingDisplayInRect:view.bounds];
        [view cacheDisplayInRect:view.bounds toBitmapImageRep:bitmap];
        [[bitmap representationUsingType:NSBitmapImageFileTypePNG properties:@{}]
            writeToURL:[self.qaDirectory URLByAppendingPathComponent:name] atomically:YES];
    }];
}
@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc > 1 && strncmp(argv[1], "--qa-dir=", 9) == 0) setenv("SMART_AUDIO_MERGE_QA_DIR", argv[1] + 9, 1);
        NSApplication *app = NSApplication.sharedApplication;
        [app setActivationPolicy:NSProcessInfo.processInfo.environment[@"SMART_AUDIO_MERGE_QA_DIR"] ? NSApplicationActivationPolicyProhibited : NSApplicationActivationPolicyRegular];
        __attribute__((objc_precise_lifetime)) MergeApp *delegate = [MergeApp new]; app.delegate = delegate;
        NSMenu *menu = [NSMenu new]; NSMenuItem *item = [NSMenuItem new]; [menu addItem:item];
        NSMenu *appMenu = [NSMenu new];
        [appMenu addItemWithTitle:@"Quit Smart Audio Merge" action:@selector(terminate:) keyEquivalent:@"q"];
        item.submenu = appMenu; app.mainMenu = menu;
        [app run];
    }
    return 0;
}
