#import <Foundation/Foundation.h>
@interface MergeEngine : NSObject
@property(atomic, strong) NSTask *task;
- (void)cancel;
- (void)run:(NSArray<NSString *> *)args event:(void (^)(NSDictionary *))event done:(void (^)(int, NSData *))done;
@end
