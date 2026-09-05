#import "Engine.h"
@implementation MergeEngine
- (void)cancel { if (self.task.running) [self.task terminate]; }
- (void)run:(NSArray<NSString *> *)args event:(void (^)(NSDictionary *))event done:(void (^)(int, NSData *))done {
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        NSTask *task = [NSTask new];
        NSPipe *out = [NSPipe pipe];
        NSString *python = @"/opt/homebrew/bin/python3";
        if (![[NSFileManager defaultManager] isExecutableFileAtPath:python]) python = @"/usr/local/bin/python3";
        task.executableURL = [NSURL fileURLWithPath:python];
        task.arguments = [@[[NSBundle.mainBundle.resourcePath stringByAppendingPathComponent:@"engine/main.py"]] arrayByAddingObjectsFromArray:args];
        NSMutableDictionary *env = [NSProcessInfo.processInfo.environment mutableCopy];
        env[@"PYTHONDONTWRITEBYTECODE"] = @"1";
        task.environment = env;
        task.standardOutput = out;
        task.standardError = NSFileHandle.fileHandleWithStandardError;
        NSError *error;
        if (![task launchAndReturnError:&error]) {
            dispatch_async(dispatch_get_main_queue(), ^{ event(@{@"event": @"error", @"message": error.localizedDescription}); done(1, [NSData data]); });
            return;
        }
        self.task = task;
        NSMutableData *all = [NSMutableData data];
        NSMutableData *pending = [NSMutableData data];
        while (YES) {
            NSData *chunk = out.fileHandleForReading.availableData;
            if (!chunk.length) break;
            [all appendData:chunk];
            [pending appendData:chunk];
            while (YES) {
                const unsigned char *bytes = pending.bytes;
                NSUInteger offset = 0;
                while (offset < pending.length && bytes[offset] != '\n') offset++;
                if (offset == pending.length) break;
                NSData *line = [pending subdataWithRange:NSMakeRange(0, offset)];
                [pending replaceBytesInRange:NSMakeRange(0, offset + 1) withBytes:NULL length:0];
                NSDictionary *value = [NSJSONSerialization JSONObjectWithData:line options:0 error:nil];
                if ([value isKindOfClass:NSDictionary.class]) dispatch_async(dispatch_get_main_queue(), ^{ event(value); });
            }
        }
        [task waitUntilExit];
        self.task = nil;
        dispatch_async(dispatch_get_main_queue(), ^{ done(task.terminationStatus, all); });
    });
}
@end
